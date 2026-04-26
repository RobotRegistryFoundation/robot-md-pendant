"""Record N seconds and play it back through the active output."""
from __future__ import annotations

import array
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


@dataclass
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
    inp: _Inputable, out: _Outputable, seconds: float, samplerate: int = 16000,
) -> LoopbackResult:
    target = int(seconds * samplerate * 2)  # bytes (s16 mono)
    await inp.start()
    buf = bytearray()
    while len(buf) < target:
        chunk = await inp.read()
        if chunk:
            buf.extend(chunk)
    await inp.stop()
    pcm = bytes(buf[:target])
    await out.start()
    await out.write(pcm)
    await out.stop()
    return LoopbackResult(
        recorded_bytes=len(pcm),
        recorded_pcm=pcm,
        peak_dbfs=_peak_dbfs(pcm),
    )
