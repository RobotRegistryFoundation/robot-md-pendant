from __future__ import annotations
import asyncio
from typing import Callable


class Watchdog:
    def __init__(self, timeout_ms: int, on_lost: Callable[[], None]) -> None:
        self._timeout = timeout_ms / 1000.0
        self._on_lost = on_lost
        self._last_ping: float = 0.0
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._last_ping = asyncio.get_event_loop().time()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def ping(self) -> None:
        self._last_ping = asyncio.get_event_loop().time()

    async def _run(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self._timeout / 3)
            if asyncio.get_event_loop().time() - self._last_ping > self._timeout:
                self._on_lost()
                return
