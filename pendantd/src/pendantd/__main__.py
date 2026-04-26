from __future__ import annotations
import asyncio
import logging
import os
from dataclasses import asdict
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
from .voice_cfg import load_voice_cfg, VoiceCfgWatcher, VoiceConfigError

log = logging.getLogger(__name__)


def _build_control_handlers(router: AudioRouter, voice_loop: VoiceLoop, cfg_path: Path) -> dict:
    """Build the IPC handler dict for ControlSocketServer.

    Handlers wired here:
      audio.list_devices, audio.get_active, audio.set_input, audio.set_output,
      audio.test_loopback, audio.test_tts,
      voice.start, voice.stop, voice.status, voice.set_wake_aliases, voice.test_wake

    Test handlers (audio.test_loopback, audio.test_tts) pause wake matching for
    exclusive router access, then resume on exit.
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
        return {"matched": asdict(matched) if matched else None, "persisted": True}

    def _set_aliases(params: dict) -> dict:
        aliases = [a for a in params.get("aliases", []) if isinstance(a, str)]
        _cfg_set("wake_aliases", aliases)
        base = ["claude"]
        voice_loop.wake.set_vocabulary(base + aliases)
        return {"vocabulary": list(voice_loop.wake.vocabulary), "persisted": True}

    async def _audio_test_loopback(params: dict) -> dict:
        from .audio.loopback import record_and_play
        seconds = float(params.get("seconds", 2.0))
        # Pause wake matching so the test gets exclusive use of the router.
        was_paused = voice_loop.paused
        voice_loop.pause()
        try:
            class _RouterIn:
                async def start(self): pass
                async def read(self): return await router.read()
                async def stop(self): pass
            class _RouterOut:
                async def start(self): pass
                async def write(self, b): await router.write(b)
                async def stop(self): pass
            result = await record_and_play(_RouterIn(), _RouterOut(), seconds=seconds)
            return {
                "recorded_bytes": result.recorded_bytes,
                "played": True,
                "peak_dbfs": result.peak_dbfs,
            }
        finally:
            if not was_paused:
                voice_loop.resume()

    async def _audio_test_tts(params: dict) -> dict:
        text = params.get("text", "hello")
        was_paused = voice_loop.paused
        voice_loop.pause()
        played = 0
        try:
            piper = voice_loop.piper  # already wired
            async for chunk in piper.synthesize(text):
                await router.write(chunk)
                played += len(chunk)
        finally:
            if not was_paused:
                voice_loop.resume()
        return {
            "played": True,
            "duration_ms": int(played / (16000 * 2) * 1000),  # bytes → ms at 16k mono s16
            "voice": getattr(piper, "voice", "default"),
        }

    async def _voice_test_wake(params: dict) -> dict:
        timeout_s = float(params.get("timeout_seconds", 10.0))
        # Snapshot last_wake_at; collect any new wakes during the window.
        baseline = voice_loop.last_wake_at
        event_loop = asyncio.get_event_loop()
        deadline = event_loop.time() + timeout_s
        matches: list[dict] = []
        while event_loop.time() < deadline:
            await asyncio.sleep(0.2)
            if voice_loop.last_wake_at is not None and voice_loop.last_wake_at != baseline:
                matches.append({
                    "phrase": voice_loop.last_wake_phrase or "(detected)",
                    "timestamp_s": voice_loop.last_wake_at,
                })
                baseline = voice_loop.last_wake_at
        return {"matches": matches}

    return {
        "audio.list_devices": lambda p: {
            "inputs": [asdict(d) for d in list_devices().inputs],
            "outputs": [asdict(d) for d in list_devices().outputs],
        },
        "audio.get_active": lambda p: {
            "input": asdict(router.active_input) if router.active_input else None,
            "output": asdict(router.active_output) if router.active_output else None,
            "source": "pinned" if (router.pin_in or router.pin_out) else "auto",
        },
        "audio.set_input": lambda p: _set_pin("input", p),
        "audio.set_output": lambda p: _set_pin("output", p),
        "audio.test_loopback": _audio_test_loopback,
        "audio.test_tts": _audio_test_tts,
        # voice.start resumes wake matching; voice.stop pauses it.
        # The VoiceLoop.run() coroutine stays alive — pause only suspends audio reads.
        "voice.start": lambda p: (voice_loop.resume(), {"state": voice_loop.state.value, "paused": False})[1],
        "voice.stop": lambda p: (voice_loop.pause(), {"state": voice_loop.state.value, "paused": True})[1],
        "voice.status": lambda p: {
            "state": voice_loop.state.value,
            "vocabulary": list(voice_loop.wake.vocabulary),
            "current_input": asdict(router.active_input) if router.active_input else None,
            "current_output": asdict(router.active_output) if router.active_output else None,
            "last_wake_at": voice_loop.last_wake_at,
            "last_wake_phrase": voice_loop.last_wake_phrase,
            "last_utterance": voice_loop.last_utterance,
            "latency_ms": voice_loop.last_latency_ms,
        },
        "voice.set_wake_aliases": _set_aliases,
        "voice.test_wake": _voice_test_wake,
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
    robot_md_path = os.environ.get("ROBOT_MD_PATH")
    if not robot_md_path:
        log.error(
            "ROBOT_MD_PATH environment variable is required (path to ROBOT.md). "
            "Set it via systemd Environment= or shell export. Example: "
            "ROBOT_MD_PATH=/home/pi/robot/ROBOT.md"
        )
        return 2
    mcp = MCPBridge(command=["npx", "robot-md-mcp", "--robot", robot_md_path])
    await mcp.start()
    try:
        server = Server(host="0.0.0.0", port=8765, mcp=mcp, buttons=buttons)

        voice_loop: VoiceLoop | None = None
        router: AudioRouter | None = None
        watcher: DeviceWatcher | None = None
        cfg_watcher: VoiceCfgWatcher | None = None
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

            # VoiceAgent wraps the Claude Agent SDK, fulfilling VoiceLoop's
            # query(text) -> str contract. MCP server wires robot-md-mcp so the
            # agent can read ROBOT.md and drive robot tools via voice commands.
            from .voice.agent_adapter import VoiceAgent
            agent = VoiceAgent(
                system_prompt=(
                    "You control a robot via MCP tools. Keep replies short — "
                    "one or two sentences — since they're spoken aloud. "
                    f"The robot is described in {robot_md_path}."
                ),
                mcp_servers={
                    "robot-md": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["robot-md-mcp", "--robot", robot_md_path],
                    },
                },
            )

            voice_loop = VoiceLoop(
                router=router,
                wake=wake,
                endpoint_factory=make_endpoint,
                whisper=whisper,
                agent=agent,
                piper=piper,
            )

            def _on_voice_cfg_change(new_cfg: dict) -> None:
                assert router is not None and voice_loop is not None
                pin_changed = False
                if new_cfg.get("input_device") != cfg["input_device"]:
                    router.set_pin("input", new_cfg["input_device"] or "")
                    pin_changed = True
                if new_cfg.get("output_device") != cfg["output_device"]:
                    router.set_pin("output", new_cfg["output_device"] or "")
                    pin_changed = True
                if pin_changed:
                    asyncio.create_task(router.update(list_devices()))
                new_vocab = ["claude"]
                if new_cfg.get("robot_name"):
                    new_vocab.append(new_cfg["robot_name"])
                new_vocab.extend(new_cfg.get("wake_aliases", []))
                if new_vocab != list(voice_loop.wake.vocabulary):
                    voice_loop.wake.set_vocabulary(new_vocab)
                if new_cfg.get("sample_rate") != cfg["sample_rate"] or new_cfg.get("tts_voice") != cfg["tts_voice"]:
                    log.warning("voice.yaml: sample_rate/tts_voice changes require pendantd restart")
                cfg.clear()
                cfg.update(new_cfg)

            cfg_watcher = VoiceCfgWatcher(cfg_path, on_change=_on_voice_cfg_change)
            await cfg_watcher.start()

            async def on_device_change(reason: str) -> None:
                assert router is not None and voice_loop is not None
                new_devs = list_devices()
                prev_in = router.active_input.name if router.active_input else None
                prev_out = router.active_output.name if router.active_output else None
                await router.update(new_devs)
                new_in = router.active_input.name if router.active_input else None
                new_out = router.active_output.name if router.active_output else None

                if reason == "pendant-connected":
                    await voice_loop.announce("Pendant connected.")
                elif reason == "pendant-disconnected":
                    await voice_loop.announce("Pendant disconnected.")
                elif new_out and new_out != prev_out:
                    await voice_loop.announce(f"Now using {new_out}.")
                elif prev_out and not new_out:
                    await voice_loop.announce("Switched to built-in audio.")
                elif new_in and new_in != prev_in:
                    # Quieter notice for input-only changes
                    log.info("input device changed: %s -> %s", prev_in, new_in)

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
        if cfg_watcher is not None:
            await cfg_watcher.stop()
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
