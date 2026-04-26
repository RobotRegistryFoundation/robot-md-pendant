import asyncio
import pytest
from pendantd.audio.loopback import record_and_play


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
