"""VoiceLoop — orchestrates wake → endpoint → utterance ASR → agent → TTS."""
from __future__ import annotations

import asyncio
import enum
from typing import Any, Callable, Protocol


class LoopState(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class _Router(Protocol):
    active_input: Any
    active_output: Any
    async def read(self) -> bytes: ...
    async def write(self, chunk: bytes) -> None: ...


class _WakeMatcher(Protocol):
    vocabulary: list[str]
    def feed(self, pcm: bytes) -> list[dict]: ...
    def set_vocabulary(self, v: list[str]) -> None: ...


class VoiceLoop:
    def __init__(
        self,
        router: _Router,
        wake: _WakeMatcher,
        endpoint_factory: Callable[[Callable[[], None]], Any],
        whisper: Any,
        agent: Any,
        piper: Any,
        wake_window_seconds: float = 1.5,
        wake_step_seconds: float = 0.5,
        sample_rate: int = 16000,
    ) -> None:
        self._router = router
        self._wake = wake
        self._make_endpoint = endpoint_factory
        self._whisper = whisper
        self._agent = agent
        self._piper = piper
        self._sr = sample_rate
        self._win_bytes = int(wake_window_seconds * sample_rate * 2)
        self._step_bytes = int(wake_step_seconds * sample_rate * 2)
        self.state = LoopState.IDLE
        self.history: list[LoopState] = []
        self.last_wake_at: float | None = None
        self.last_utterance: str = ""
        self._stop = asyncio.Event()
        self._announce_q: asyncio.Queue[str] = asyncio.Queue()

    def _set_state(self, s: LoopState) -> None:
        self.state = s
        self.history.append(s)

    async def announce(self, text: str) -> None:
        await self._announce_q.put(text)

    async def stop(self) -> None:
        self._stop.set()

    async def _speak(self, text: str) -> None:
        async for chunk in self._piper.synthesize(text):
            await self._router.write(chunk)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        rolling = bytearray()
        bytes_since_step = 0
        self._set_state(LoopState.LISTENING)
        while not self._stop.is_set():
            # Drain announcements first (cuts mid-listen)
            try:
                msg = self._announce_q.get_nowait()
                self._set_state(LoopState.SPEAKING)
                await self._speak(msg)
                self._set_state(LoopState.LISTENING)
            except asyncio.QueueEmpty:
                pass

            try:
                chunk = await asyncio.wait_for(self._router.read(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            rolling.extend(chunk)
            if len(rolling) > self._win_bytes:
                del rolling[: len(rolling) - self._win_bytes]
            bytes_since_step += len(chunk)
            if bytes_since_step < self._step_bytes:
                continue
            bytes_since_step = 0

            hits = self._wake.feed(bytes(rolling))
            if not hits:
                continue

            self.last_wake_at = loop.time()
            # Capture utterance until endpoint fires
            self._set_state(LoopState.THINKING)
            utt = bytearray()
            done = asyncio.Event()
            ep = self._make_endpoint(done.set)  # factory: (on_end) -> endpoint
            while not done.is_set():
                try:
                    c = await asyncio.wait_for(self._router.read(), timeout=2.5)
                except asyncio.TimeoutError:
                    break
                utt.extend(c)
                ep.feed(c)
            transcript = await self._whisper.transcribe(bytes(utt))
            self.last_utterance = transcript
            reply = await self._agent.query(transcript)
            self._set_state(LoopState.SPEAKING)
            await self._speak(reply)
            self._set_state(LoopState.LISTENING)
            rolling.clear()
        self._set_state(LoopState.IDLE)
