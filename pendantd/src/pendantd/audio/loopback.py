"""Record N seconds and play it back through the active output."""
from __future__ import annotations

import array
import asyncio
import math
from dataclasses import dataclass
from typing import Protocol


class _Inputable(Protocol):
    async def start(self) -> None: ...
    async def read(self) -> bytes: ...
    async def stop(self) -> None: ...


class _Outputable(Protocol):
    async def start(self) -> None: ...
    async def write(self, chunk: bytes) -> None: ...
    async def stop(self) -> None: ...


@dataclass(frozen=True)
class LoopbackResult:
    recorded_bytes: int
    recorded_pcm: bytes
    peak_dbfs: float


def _peak_dbfs(pcm: bytes) -> float:
    if not pcm:
        return -120.0
    samples = array.array("h"); samples.frombytes(pcm)
    peak = max((abs(s) for s in samples), default=0)
    if peak == 0:
        return -120.0
    return 20.0 * math.log10(peak / 32768.0)


async def record_and_play(
    inp: _Inputable,
    out: _Outputable,
    seconds: float,
    samplerate: int = 16000,
    read_timeout: float = 1.0,
) -> LoopbackResult:
    """Record up to `seconds` of audio, then play it back.

    `read_timeout` bounds each individual `inp.read()` call. If a single read
    takes longer than `read_timeout`, the recording loop exits early and
    returns whatever was captured (may be shorter than the requested duration).
    This prevents hangs when the input stream stalls or the device disappears.
    """
    target = int(seconds * samplerate * 2)  # bytes (s16 mono)
    await inp.start()
    buf = bytearray()
    try:
        while len(buf) < target:
            try:
                chunk = await asyncio.wait_for(inp.read(), timeout=read_timeout)
            except asyncio.TimeoutError:
                break
            if chunk:
                buf.extend(chunk)
            else:
                # Empty chunk — input stream is alive but producing nothing.
                # Yield once so a slow producer can fill the queue, then check again.
                await asyncio.sleep(0)
    finally:
        await inp.stop()
    pcm = bytes(buf[:target])
    await out.start()
    if pcm:
        await out.write(pcm)
    await out.stop()
    return LoopbackResult(
        recorded_bytes=len(pcm),
        recorded_pcm=pcm,
        peak_dbfs=_peak_dbfs(pcm),
    )
