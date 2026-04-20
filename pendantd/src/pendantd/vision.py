from __future__ import annotations
import asyncio
import base64
from typing import Callable

class ThumbnailProducer:
    def __init__(self, grab: Callable[[], bytes], fps: float, on_frame: Callable[[dict], None]) -> None:
        self._grab = grab
        self._period = 1.0 / fps
        self._on = on_frame
        self._task: asyncio.Task | None = None
        self._stop = False

    async def start(self) -> None:
        self._stop = False
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop:
            try:
                jpeg = self._grab()
                self._on({"v": 1, "type": "thumbnail", "b64": base64.b64encode(jpeg).decode(), "w": 160, "h": 120})
            except Exception:
                pass
            await asyncio.sleep(self._period)
