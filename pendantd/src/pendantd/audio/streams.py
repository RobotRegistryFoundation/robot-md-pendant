"""Async wrappers over sounddevice.RawInputStream / RawOutputStream."""
from __future__ import annotations

import asyncio
from typing import Any, Callable


def _default_input_factory(**kw: Any) -> Any:  # pragma: no cover - thin wrapper
    import sounddevice as sd
    return sd.RawInputStream(**kw)


def _default_output_factory(**kw: Any) -> Any:  # pragma: no cover
    import sounddevice as sd
    return sd.RawOutputStream(**kw)


class InputStream:
    """16 kHz mono int16 capture, queue-backed for asyncio consumers."""

    def __init__(
        self,
        device_index: int,
        samplerate: int = 16000,
        blocksize: int = 1600,  # 100 ms @ 16 kHz
        _factory: Callable[..., Any] = _default_input_factory,
    ) -> None:
        self._device = device_index
        self._sr = samplerate
        self._block = blocksize
        self._factory = _factory
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self._stream: Any = None

    def _on_block(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        if self._loop is None:
            return
        chunk = bytes(indata)
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
        except asyncio.QueueFull:
            # Drop oldest under back-pressure
            try:
                self._queue.get_nowait()
                self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
            except Exception:
                pass

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stream = self._factory(
            samplerate=self._sr, channels=1, dtype="int16",
            callback=self._on_block, device=self._device, blocksize=self._block,
        )
        self._stream.start()

    async def read(self) -> bytes:
        return await self._queue.get()

    async def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class OutputStream:
    """16 kHz mono int16 playback."""

    def __init__(
        self,
        device_index: int,
        samplerate: int = 16000,
        _factory: Callable[..., Any] = _default_output_factory,
    ) -> None:
        self._device = device_index
        self._sr = samplerate
        self._factory = _factory
        self._stream: Any = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._stream = self._factory(
            samplerate=self._sr, channels=1, dtype="int16",
            device=self._device, blocksize=0,
        )
        self._stream.start()

    async def write(self, chunk: bytes) -> None:
        if self._stream is None:
            raise RuntimeError("OutputStream not started")
        async with self._lock:
            self._stream.write(chunk)

    async def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
