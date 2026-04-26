import asyncio
import pytest
from pendantd.voice.loop import VoiceLoop, LoopState


class FakeRouter:
    def __init__(self, frames):
        self._frames = list(frames)
        self.written: list[bytes] = []
        self.active_input = type("D", (), {"name": "fake-mic"})()
        self.active_output = type("D", (), {"name": "fake-spkr"})()
    async def read(self):
        if not self._frames:
            await asyncio.sleep(0.5)
            return b"\x00" * 320
        return self._frames.pop(0)
    async def write(self, b): self.written.append(bytes(b))


class StubWake:
    def __init__(self, fire_after_n_frames: int):
        self._n = fire_after_n_frames
        self._count = 0
        self.vocabulary = ["claude", "bob"]
    def feed(self, pcm):
        self._count += 1
        if self._count == self._n:
            return [{"phrase": "bob", "transcript": "bob pick the lego"}]
        return []
    def set_vocabulary(self, v): self.vocabulary = list(v)


class StubEndpoint:
    """Fires on_end after `fire_after` feed() calls."""
    def __init__(self, on_end, fire_after: int = 2):
        self._on_end = on_end
        self._fire_after = fire_after
        self._n = 0
    def feed(self, chunk):
        self._n += 1
        if self._n >= self._fire_after:
            self._on_end()


class StubWhisper:
    async def transcribe(self, pcm): return "pick the lego"


class StubAgent:
    def __init__(self): self.calls: list[str] = []
    async def query(self, text: str) -> str:
        self.calls.append(text)
        return "okay, picking the lego"


class StubPiper:
    async def synthesize(self, text):
        yield b"\x10\x00" * 100
        yield b"\x20\x00" * 100
    async def cancel(self): pass


@pytest.mark.asyncio
async def test_voice_loop_state_transitions_on_wake():
    frames = [b"\x00" * 320 for _ in range(20)]
    router = FakeRouter(frames)
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=2),
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=2),
        whisper=StubWhisper(), agent=StubAgent(), piper=StubPiper(),
        wake_step_seconds=0.01,  # small step so test runs fast
    )
    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.3)
    await loop.stop()
    await task
    assert LoopState.LISTENING in loop.history
    assert LoopState.THINKING in loop.history
    assert LoopState.SPEAKING in loop.history
    assert router.written  # TTS played


@pytest.mark.asyncio
async def test_voice_loop_announces_on_router_change():
    router = FakeRouter([b"\x00" * 320])
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=999),
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=999),
        whisper=StubWhisper(), agent=StubAgent(), piper=StubPiper(),
    )
    task = asyncio.create_task(loop.run())
    await loop.announce("Now using fake-spkr.")
    await asyncio.sleep(0.1)
    await loop.stop()
    await task
    assert any(b for b in router.written)  # announcement played
