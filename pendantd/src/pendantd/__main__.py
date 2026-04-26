from __future__ import annotations
import asyncio
import logging
import os
from pathlib import Path

from .server import Server, ControlSocketServer
from .mcp_bridge import MCPBridge
from .buttons import load_buttons
from .audio.devices import list_devices, match_substring
from .audio.router import AudioRouter
from .audio.watcher import DeviceWatcher
from .voice.endpoint import Endpointer
from .voice.loop import VoiceLoop
from .voice.piper import Piper
from .voice.wake import StreamingWakeMatcher
from .voice.whisper import Whisper
from .voice_cfg import load_voice_cfg, VoiceConfigError

log = logging.getLogger(__name__)


def _build_control_handlers(router: AudioRouter, voice_loop: VoiceLoop, cfg_path: Path) -> dict:
    """Build the IPC handler dict for ControlSocketServer.

    Handlers wired here:
      audio.list_devices, audio.get_active, audio.set_input, audio.set_output,
      voice.start, voice.stop, voice.status, voice.set_wake_aliases, voice.test_wake

    TODO (Task 14): audio.test_loopback and audio.test_tts are not yet wired.
    Both require briefly holding the mic/speaker and are better surfaced through
    the MCP server layer rather than raw IPC. Deferred to Task 14.
    """
    import yaml as _yaml

    def _cfg_set(key: str, value: object) -> None:
        data = _yaml.safe_load(cfg_path.read_text()) or {}
        data[key] = value
        cfg_path.write_text(_yaml.safe_dump(data))

    def _set_pin(kind: str, params: dict) -> dict:
        substring = params.get("substring") or ""
        devs = list_devices()
        pool = devs.inputs if kind == "input" else devs.outputs
        matched = match_substring(pool, substring)
        router.set_pin(kind, substring)
        cfg_key = "input_device" if kind == "input" else "output_device"
        _cfg_set(cfg_key, substring)
        return {"matched": matched.__dict__ if matched else None, "persisted": True}

    def _set_aliases(params: dict) -> dict:
        aliases = [a for a in params.get("aliases", []) if isinstance(a, str)]
        _cfg_set("wake_aliases", aliases)
        base = ["claude"]
        voice_loop._wake.set_vocabulary(base + aliases)
        return {"vocabulary": list(voice_loop._wake.vocabulary), "persisted": True}

    return {
        "audio.list_devices": lambda p: {
            "inputs": [d.__dict__ for d in list_devices().inputs],
            "outputs": [d.__dict__ for d in list_devices().outputs],
        },
        "audio.get_active": lambda p: {
            "input": router.active_input.__dict__ if router.active_input else None,
            "output": router.active_output.__dict__ if router.active_output else None,
            "source": "pinned" if (router._pin_in or router._pin_out) else "auto",
        },
        "audio.set_input": lambda p: _set_pin("input", p),
        "audio.set_output": lambda p: _set_pin("output", p),
        # voice.start / voice.stop return current state; actual start/stop is
        # lifecycle-managed (VoiceLoop.run() is always running while daemon is up).
        "voice.start": lambda p: {"state": voice_loop.state.value},
        "voice.stop": lambda p: {"state": voice_loop.state.value},
        "voice.status": lambda p: {
            "state": voice_loop.state.value,
            "vocabulary": list(voice_loop._wake.vocabulary),
            "current_input": router.active_input.__dict__ if router.active_input else None,
            "current_output": router.active_output.__dict__ if router.active_output else None,
            "last_wake_at": voice_loop.last_wake_at,
            "last_utterance": voice_loop.last_utterance,
        },
        "voice.set_wake_aliases": _set_aliases,
        # voice.test_wake: live capture deferred — call the MCP-side helper in Task 14.
        "voice.test_wake": lambda p: {"matches": []},
    }


async def async_main() -> int:
    cfg_dir = Path(os.environ.get("PENDANTD_CONFIG", str(Path.home() / ".config" / "robot-md-pendant")))
    cfg_path = cfg_dir / "voice.yaml"

    # Load voice config; fall back to minimal defaults if file absent so the
    # daemon can still serve WS without voice hardware configured yet.
    try:
        cfg = load_voice_cfg(cfg_path)
    except (FileNotFoundError, VoiceConfigError) as exc:
        log.warning("voice.yaml not loaded (%s); voice pipeline disabled", exc)
        cfg = None

    buttons = load_buttons(cfg_dir / "buttons.yaml")
    robot_md_path = os.environ["ROBOT_MD_PATH"]
    mcp = MCPBridge(command=["npx", "robot-md-mcp", "--robot", robot_md_path])
    await mcp.start()
    try:
        server = Server(host="0.0.0.0", port=8765, mcp=mcp, buttons=buttons)

        voice_loop: VoiceLoop | None = None
        router: AudioRouter | None = None
        watcher: DeviceWatcher | None = None
        control: ControlSocketServer | None = None

        if cfg is not None:
            # Build AudioRouter — streams are lazy; attach() opens them.
            router = AudioRouter(
                pinned_input=cfg["input_device"],
                pinned_output=cfg["output_device"],
                samplerate=cfg["sample_rate"],
            )
            # attach() must run INSIDE the running loop (DeviceWatcher requires it too).
            await router.attach(list_devices())

            # faster-whisper model for streaming wake detection.
            # WhisperModel("tiny.en") will try to download ~75 MB on first use.
            # On a Pi without internet this will fail — see README for offline setup.
            from faster_whisper import WhisperModel
            fw = WhisperModel("tiny.en", compute_type="int8")

            # NOTE: cfg["wake_word"] is intentionally not added to vocabulary here —
            # it's a legacy boolean/path field. Vocabulary = "claude" + robot_name +
            # wake_aliases. wake_word is tracked separately by callers that use a
            # dedicated wake-word binary (e.g., openWakeWord). See voice_cfg.py.
            vocab = ["claude"]
            if cfg.get("robot_name"):
                vocab.append(cfg["robot_name"])
            vocab.extend(cfg.get("wake_aliases", []))
            wake = StreamingWakeMatcher(model=fw, vocabulary=vocab)

            def make_endpoint(on_end: object) -> Endpointer:
                return Endpointer(rms_threshold=200, silence_ms=300, on_end=on_end)  # type: ignore[arg-type]

            whisper = Whisper(
                command=cfg.get(
                    "whisper_cmd",
                    ["whisper-cpp", "-m", "/usr/local/share/whisper/ggml-base.en.bin", "-"],
                )
            )
            piper = Piper(
                command=cfg.get(
                    "piper_cmd",
                    ["piper", "--model", cfg["tts_voice"]],
                )
            )

            # Agent: VoiceLoop.query() protocol differs from AgentSession.run_turn()
            # (query returns a string; run_turn yields typed events). Wiring the full
            # agent adapter is deferred to Task 14 (MCP server). Pass None for now —
            # VoiceLoop will short-circuit at _handle_utterance if agent is None.
            agent = None

            voice_loop = VoiceLoop(
                router=router,
                wake=wake,
                endpoint_factory=make_endpoint,
                whisper=whisper,
                agent=agent,
                piper=piper,
            )

            async def on_device_change(reason: str) -> None:
                assert router is not None and voice_loop is not None
                new_devs = list_devices()
                prev_out = router.active_output.name if router.active_output else None
                await router.update(new_devs)
                new_out = router.active_output.name if router.active_output else None
                if new_out and new_out != prev_out:
                    await voice_loop.announce(f"Now using {new_out}.")

            # DeviceWatcher must be created inside the running asyncio loop.
            watcher = DeviceWatcher(on_change=on_device_change, debounce_ms=300)

            # Wire pendant connect/disconnect events from Server into DeviceWatcher.
            server.on_pendant_connect = watcher.on_pendant_connect
            server.on_pendant_disconnect = watcher.on_pendant_disconnect

            # IPC control socket — parent dir created by tmpfiles.d (Task 17).
            # Path /run/pendantd/control.sock is documented in README.
            control = ControlSocketServer(
                path="/run/pendantd/control.sock",
                handlers=_build_control_handlers(router, voice_loop, cfg_path),
            )
            await control.start()

        async with server.run() as addr:
            print(f"pendantd listening on {addr}")
            if voice_loop is not None:
                # Run voice pipeline alongside the WS server. If voice_loop.run()
                # raises, the exception propagates through gather and shuts down.
                await asyncio.gather(
                    voice_loop.run(),
                    asyncio.Future(),  # run forever until KeyboardInterrupt / SIGTERM
                    return_exceptions=False,
                )
            else:
                await asyncio.Future()  # run forever (no voice pipeline)

    finally:
        if control is not None:
            await control.stop()
        if watcher is not None:
            await watcher.stop()
        if router is not None:
            await router.shutdown()
        await mcp.stop()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        return asyncio.run(async_main()) or 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
