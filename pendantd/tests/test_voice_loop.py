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


@pytest.mark.asyncio
async def test_voice_loop_survives_agent_exception():
    """An exception in agent.query must not kill the loop."""
    class BoomAgent:
        def __init__(self): self.calls = 0
        async def query(self, text):
            self.calls += 1
            raise RuntimeError("agent crashed")

    frames = [b"\x00" * 320 for _ in range(40)]
    router = FakeRouter(frames)
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=2),
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=2),
        whisper=StubWhisper(), agent=BoomAgent(), piper=StubPiper(),
        wake_step_seconds=0.01,
    )
    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.3)
    await loop.stop()
    await task
    # Loop must have returned to LISTENING after the failure
    assert LoopState.LISTENING in loop.history
    assert LoopState.IDLE == loop.state


@pytest.mark.asyncio
async def test_voice_loop_stop_during_thinking_returns_promptly():
    """stop() while a slow agent.query is in flight must cancel it."""
    cancelled: list[bool] = []

    class SlowAgent:
        async def query(self, text):
            try:
                await asyncio.sleep(30)
                return "should not get here"
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

    frames = [b"\x00" * 320 for _ in range(40)]
    router = FakeRouter(frames)
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=2),
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=2),
        whisper=StubWhisper(), agent=SlowAgent(), piper=StubPiper(),
        wake_step_seconds=0.01,
    )
    task = asyncio.create_task(loop.run())
    # Give it time to wake and enter THINKING
    await asyncio.sleep(0.3)
    # Now stop — should NOT take 30s
    t0 = asyncio.get_running_loop().time()
    await loop.stop()
    await asyncio.wait_for(task, timeout=1.0)
    elapsed = asyncio.get_running_loop().time() - t0
    assert elapsed < 1.0, f"stop took {elapsed:.2f}s — pipeline did not cancel"
    assert cancelled == [True]
    assert loop.state == LoopState.IDLE


@pytest.mark.asyncio
async def test_voice_loop_history_is_bounded():
    """history is a deque(maxlen=64); should not grow unbounded."""
    router = FakeRouter([b"\x00" * 320 for _ in range(200)])
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=99999),  # never fires
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=999),
        whisper=StubWhisper(), agent=StubAgent(), piper=StubPiper(),
    )
    # Manually thrash the state to fill history past 64
    for _ in range(200):
        loop._set_state(LoopState.LISTENING)
    assert len(loop.history) <= 64


@pytest.mark.asyncio
async def test_voice_loop_pause_blocks_wake_handling():
    """When paused, wake hits don't trigger the utterance pipeline."""
    frames = [b"\x00" * 320 for _ in range(40)]
    router = FakeRouter(frames)
    agent = StubAgent()
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=2),
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=2),
        whisper=StubWhisper(), agent=agent, piper=StubPiper(),
        wake_step_seconds=0.01,
    )
    loop.pause()  # pause BEFORE starting
    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.3)
    await loop.stop()
    await task
    # Agent should NOT have been called while paused
    assert agent.calls == []


@pytest.mark.asyncio
async def test_voice_loop_resume_after_pause():
    frames = [b"\x00" * 320 for _ in range(40)]
    router = FakeRouter(frames)
    agent = StubAgent()
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=2),
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=2),
        whisper=StubWhisper(), agent=agent, piper=StubPiper(),
        wake_step_seconds=0.01,
    )
    loop.pause()
    assert loop.paused is True
    loop.resume()
    assert loop.paused is False


@pytest.mark.asyncio
async def test_voice_loop_tracks_latency_ms_after_handle_utterance():
    """After a wake → response cycle, last_latency_ms reflects the elapsed time."""
    frames = [b"\x00" * 320 for _ in range(40)]
    router = FakeRouter(frames)
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=2),
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=2),
        whisper=StubWhisper(), agent=StubAgent(), piper=StubPiper(),
        wake_step_seconds=0.01,
    )
    assert loop.last_latency_ms is None
    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.4)
    await loop.stop()
    await task
    assert loop.last_latency_ms is not None
    assert loop.last_latency_ms > 0  # measurable elapsed time
