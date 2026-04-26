import asyncio
import pytest
from pendantd.audio.streams import InputStream, OutputStream


class FakeSDInput:
    def __init__(self, samplerate, channels, dtype, callback, device, blocksize):
        self._cb = callback
        self._task = None
        self.started = False
        self.stopped = False

    def start(self): self.started = True
    def stop(self): self.stopped = True
    def close(self): pass
    def __enter__(self): self.start(); return self
    def __exit__(self, *a): self.stop()


@pytest.mark.asyncio
async def test_input_stream_yields_chunks_from_callback():
    received = []

    def make(samplerate, channels, dtype, callback, device, blocksize):
        # Simulate sounddevice firing the callback with a chunk
        import threading, time
        def fire():
            time.sleep(0.01)
            callback(b"\x00\x01" * 160, 160, None, None)
        threading.Thread(target=fire, daemon=True).start()
        return FakeSDInput(samplerate, channels, dtype, callback, device, blocksize)

    stream = InputStream(device_index=0, samplerate=16000, blocksize=160, _factory=make)
    await stream.start()
    chunk = await asyncio.wait_for(stream.read(), timeout=0.5)
    assert isinstance(chunk, (bytes, bytearray))
    assert len(chunk) == 320  # 160 samples × 2 bytes
    await stream.stop()


@pytest.mark.asyncio
async def test_output_stream_writes_chunks():
    written: list[bytes] = []

    class FakeSDOutput:
        def __init__(self, samplerate, channels, dtype, device, blocksize):
            pass
        def start(self): pass
        def stop(self): pass
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def write(self, chunk): written.append(bytes(chunk))

    stream = OutputStream(device_index=1, samplerate=16000, _factory=lambda **kw: FakeSDOutput(**kw))
    await stream.start()
    await stream.write(b"\x10\x00" * 160)
    await stream.stop()
    assert written == [b"\x10\x00" * 160]
