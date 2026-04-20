from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Callable
import yaml
from watchfiles import awatch

VALID_TYPES = {"prompt", "direct_mcp"}

class ButtonConfigError(ValueError):
    pass

def load_buttons(path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    buttons = data.get("buttons", [])
    if not isinstance(buttons, list):
        raise ButtonConfigError("'buttons' must be a list")
    for b in buttons:
        t = b.get("type")
        if t not in VALID_TYPES:
            raise ButtonConfigError(f"button {b.get('label')!r}: bad type {t!r} (expected one of {VALID_TYPES})")
        if t == "prompt" and "prompt" not in b:
            raise ButtonConfigError(f"button {b.get('label')!r}: prompt type requires 'prompt' field")
        if t == "direct_mcp":
            if "tool" not in b:
                raise ButtonConfigError(f"button {b.get('label')!r}: direct_mcp type requires 'tool' field")
    return buttons

class ButtonWatcher:
    def __init__(self, path, on_change: Callable[[list[dict]], None]) -> None:
        self._path = Path(path)
        self._on_change = on_change
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self) -> None:
        self._on_change(load_buttons(self._path))
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
                self._on_change(load_buttons(self._path))
            except ButtonConfigError:
                pass  # Keep prior config; error surfacing in a later task
