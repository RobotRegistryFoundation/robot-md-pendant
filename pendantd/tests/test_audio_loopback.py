import asyncio
import pytest
from pendantd.audio.loopback import record_and_play, LoopbackResult


class StubInput:
    def __init__(self, chunks): self._chunks = list(chunks)
    async def start(self): pass
    async def read(self):
        if not self._chunks:
            await asyncio.sleep(0.01)
            return b""
        return self._chunks.pop(0)
    async def stop(self): pass


class StubOutput:
    def __init__(self): self.written = []
    async def start(self): pass
    async def write(self, b): self.written.append(b)
    async def stop(self): pass


@pytest.mark.asyncio
async def test_record_and_play_returns_recorded_bytes_and_replays():
    inp = StubInput([b"\x01\x02" * 1600, b"\x03\x04" * 1600])  # 200 ms @ 16k
    out = StubOutput()
    result = await record_and_play(inp, out, seconds=0.2)
    assert result.recorded_bytes == 6400  # 200 ms × 16k × 2 bytes
    assert b"".join(out.written) == result.recorded_pcm
    assert isinstance(result.peak_dbfs, float)


@pytest.mark.asyncio
async def test_record_and_play_breaks_out_when_input_stalls():
    """Real InputStream.read() can block forever if no PCM arrives.
    record_and_play must time out and return what it has so far."""

    class StallingInput:
        def __init__(self):
            self.first = True
            self.stopped = False
        async def start(self): pass
        async def read(self):
            if self.first:
                self.first = False
                return b"\xab\xcd" * 800  # 100ms of audio, then stall
            # block indefinitely (mimics InputStream.read awaiting an empty queue)
            await asyncio.Event().wait()
        async def stop(self): self.stopped = True

    inp = StallingInput()
    out = StubOutput()
    result = await record_and_play(inp, out, seconds=2.0, read_timeout=0.1)
    # We requested 2s (64000 bytes) but only got the first ~100ms before timeout
    assert 0 < result.recorded_bytes < 64000
    assert inp.stopped is True
    # What we did record was played
    assert b"".join(out.written) == result.recorded_pcm


def test_loopback_result_is_frozen():
    """LoopbackResult is a value object — should not allow field mutation."""
    import dataclasses
    r = LoopbackResult(recorded_bytes=10, recorded_pcm=b"\x00" * 10, peak_dbfs=-120.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.recorded_bytes = 999  # type: ignore[misc]
