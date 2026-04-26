"""VoiceLoop — orchestrates wake → endpoint → utterance ASR → agent → TTS."""
from __future__ import annotations

import asyncio
import collections
import enum
import logging
from typing import Any, Awaitable, Callable, Protocol

log = logging.getLogger(__name__)


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
        self.history: "collections.deque[LoopState]" = collections.deque(maxlen=64)
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
        try:
            while not self._stop.is_set():
                # Drain announcements first (cuts mid-listen)
                try:
                    msg = self._announce_q.get_nowait()
                    self._set_state(LoopState.SPEAKING)
                    try:
                        await self._speak(msg)
                    except Exception:
                        log.exception("VoiceLoop: announcement playback failed")
                    self._set_state(LoopState.LISTENING)
                except asyncio.QueueEmpty:
                    pass

                try:
                    chunk = await asyncio.wait_for(self._router.read(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    log.exception("VoiceLoop: router.read failed; pausing 0.5s")
                    await asyncio.sleep(0.5)
                    continue

                rolling.extend(chunk)
                if len(rolling) > self._win_bytes:
                    del rolling[: len(rolling) - self._win_bytes]
                bytes_since_step += len(chunk)
                if bytes_since_step < self._step_bytes:
                    continue
                bytes_since_step = 0

                # Run wake matcher off the event loop — faster-whisper is sync
                # and would otherwise block announcements / IPC / DeviceWatcher.
                try:
                    hits = await asyncio.to_thread(self._wake.feed, bytes(rolling))
                except Exception:
                    log.exception("VoiceLoop: wake.feed failed; skipping window")
                    continue
                if not hits:
                    continue

                self.last_wake_at = loop.time()
                self._set_state(LoopState.THINKING)
                try:
                    await self._handle_utterance()
                except Exception:
                    log.exception("VoiceLoop: utterance pipeline failed")
                finally:
                    self._set_state(LoopState.LISTENING)
                    rolling.clear()
                    bytes_since_step = 0
        finally:
            self._set_state(LoopState.IDLE)

    async def _handle_utterance(self) -> None:
        """Capture, transcribe, query, speak. Cancellable on _stop."""
        utt = bytearray()
        done = asyncio.Event()
        ep = self._make_endpoint(done.set)
        # Capture utterance, watching _stop
        while not done.is_set() and not self._stop.is_set():
            try:
                c = await asyncio.wait_for(self._router.read(), timeout=2.5)
            except asyncio.TimeoutError:
                break
            utt.extend(c)
            ep.feed(c)
        if self._stop.is_set() or not utt:
            return
        # Transcribe (race against stop)
        transcript = await self._race_with_stop(self._whisper.transcribe(bytes(utt)))
        if transcript is None:
            return
        self.last_utterance = transcript
        # Agent query (race against stop)
        reply = await self._race_with_stop(self._agent.query(transcript))
        if reply is None:
            return
        # Speak (no race needed — _speak yields to the loop chunk-by-chunk
        # and we'll naturally finish quickly; abort handled by piper.cancel
        # in callers if needed)
        self._set_state(LoopState.SPEAKING)
        await self._speak(reply)

    async def _race_with_stop(self, awaitable: Awaitable[Any]) -> Any | None:
        """Run an awaitable; cancel and return None if _stop fires first."""
        task = asyncio.ensure_future(awaitable)
        stop_task = asyncio.ensure_future(self._stop.wait())
        done_set, pending = await asyncio.wait(
            [task, stop_task], return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task in done_set:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            return None
        # task completed first
        stop_task.cancel()
        try:
            await stop_task
        except asyncio.CancelledError:
            pass
        return task.result()
