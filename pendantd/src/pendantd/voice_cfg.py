from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

import yaml
from watchfiles import awatch

# Sidecar-only required keys. tts_voice is not in this set since rcan-spec
# v3.3 §8.7 lets the manifest's voice: block supply it (see the merge in
# load_voice_cfg below).
SIDECAR_REQUIRED = ("wake_word",)

DEFAULTS: dict = {
    "robot_name": "",
    "wake_aliases": [],
    "language": "en-US",  # rcan-spec §8.7 default
    "input_device": "",
    "output_device": "",
    "sample_rate": 16000,
}


class VoiceConfigError(ValueError):
    pass


def load_manifest_voice(manifest_path) -> dict:
    """Extract voice defaults from a ROBOT.md manifest.

    Returns a dict in the sidecar's shape so it can be layered under
    ``load_voice_cfg``. Maps ``metadata.robot_name`` → ``robot_name`` and
    the optional ``voice:`` block (rcan-spec v3.3 §8.7) →
    ``wake_aliases`` / ``tts_voice`` / ``language``.

    Returns ``{}`` when ``manifest_path`` is ``None`` or when the ``rcan``
    package is not importable (sidecar-only mode preserved for environments
    that don't depend on rcan-py).
    """
    if manifest_path is None:
        return {}
    try:
        from rcan import from_manifest
    except ImportError:
        return {}

    info = from_manifest(manifest_path)
    out: dict = {}
    if info.robot_name:
        out["robot_name"] = info.robot_name
    if info.voice:
        if "aliases" in info.voice:
            out["wake_aliases"] = list(info.voice["aliases"])
        if "tts_voice" in info.voice:
            out["tts_voice"] = info.voice["tts_voice"]
        if "language" in info.voice:
            out["language"] = info.voice["language"]
    return out


def load_voice_cfg(path, manifest_path=None) -> dict:
    """Load voice config with layered precedence.

    Layers (lowest → highest):
      1. Hardcoded ``DEFAULTS``
      2. Manifest ``voice:`` block (rcan-spec §8.7) when ``manifest_path`` set
      3. Sidecar ``voice.yaml``

    Sidecar values override manifest values, which override defaults.
    Pass ``manifest_path=None`` (the default) for the original sidecar-only
    behavior.

    ``wake_word`` MUST appear in the sidecar — manifest voice block doesn't
    carry it (the `name` field is the primary wake word; `aliases` are
    extras). ``tts_voice`` is required after merge but MAY come from either
    layer.
    """
    sidecar = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(sidecar, dict):
        raise VoiceConfigError("voice config must be a mapping")

    for key in SIDECAR_REQUIRED:
        if key not in sidecar:
            raise VoiceConfigError(f"missing required key: {key!r} (sidecar)")

    manifest_defaults = load_manifest_voice(manifest_path)

    out: dict = {
        k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()
    }
    out.update(manifest_defaults)
    out.update(sidecar)

    if "tts_voice" not in out:
        raise VoiceConfigError(
            "missing required key: 'tts_voice' — provide in sidecar voice.yaml "
            "or in the ROBOT.md voice: block"
        )

    return out


class VoiceCfgWatcher:
    def __init__(
        self,
        path,
        on_change: Callable[[dict], None],
        manifest_path=None,
    ) -> None:
        self._path = Path(path)
        self._manifest_path = manifest_path
        self._on_change = on_change
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self) -> None:
        self._on_change(load_voice_cfg(self._path, self._manifest_path))
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._watch())
        # Give watchfiles time to spin up its underlying watcher so changes
        # made by the caller right after start() aren't missed.
        await asyncio.sleep(0.2)

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watch(self) -> None:
        assert self._stop_event is not None
        async for _changes in awatch(self._path, stop_event=self._stop_event, step=50):
            try:
                self._on_change(load_voice_cfg(self._path, self._manifest_path))
            except VoiceConfigError:
                pass  # Keep prior config; error surfacing in a later task
