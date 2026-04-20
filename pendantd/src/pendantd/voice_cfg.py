from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Callable
import yaml
from watchfiles import awatch

REQUIRED_KEYS = ("wake_word", "tts_voice")

class VoiceConfigError(ValueError):
    pass

def load_voice_cfg(path) -> dict:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(data, dict):
        raise VoiceConfigError("voice config must be a mapping")
    for key in REQUIRED_KEYS:
        if key not in data:
            raise VoiceConfigError(f"missing required key: {key!r}")
    return data

class VoiceCfgWatcher:
    def __init__(self, path, on_change: Callable[[dict], None]) -> None:
        self._path = Path(path)
        self._on_change = on_change
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self) -> None:
        self._on_change(load_voice_cfg(self._path))
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
                self._on_change(load_voice_cfg(self._path))
            except VoiceConfigError:
                pass  # Keep prior config; error surfacing in a later task
