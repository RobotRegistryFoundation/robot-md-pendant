from __future__ import annotations
import array
import math
from typing import Callable

class Endpointer:
    def __init__(self, rms_threshold: float, silence_ms: int, on_end: Callable[[], None]) -> None:
        self._thr = rms_threshold
        self._silence_budget_ms = silence_ms
        self._silence_ms = 0
        self._on_end = on_end
        self._fired = False
        self._had_voice = False

    def feed(self, chunk: bytes) -> None:
        if self._fired:
            return
        samples = array.array("h")
        samples.frombytes(chunk)
        if not samples:
            return
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        chunk_ms = int(1000 * len(samples) / 16000)
        if rms >= self._thr:
            self._had_voice = True
            self._silence_ms = 0
        else:
            self._silence_ms += chunk_ms
        if self._had_voice and self._silence_ms >= self._silence_budget_ms:
            self._fired = True
            self._on_end()
