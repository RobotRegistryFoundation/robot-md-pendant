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


@pytest.mark.asyncio
async def test_input_stream_start_is_idempotent():
    """Double-start must not create a second underlying stream."""
    created = []

    def make(samplerate, channels, dtype, callback, device, blocksize):
        s = FakeSDInput(samplerate, channels, dtype, callback, device, blocksize)
        created.append(s)
        return s

    stream = InputStream(device_index=0, samplerate=16000, blocksize=160, _factory=make)
    await stream.start()
    await stream.start()  # second call should be a no-op
    assert len(created) == 1
    await stream.stop()


@pytest.mark.asyncio
async def test_input_stream_drops_oldest_when_queue_full():
    """When the queue is full, the oldest chunk is dropped to make room for the new one."""
    stream = InputStream(
        device_index=0, samplerate=16000, blocksize=160,
        _factory=lambda **kw: FakeSDInput(
            samplerate=kw["samplerate"], channels=kw["channels"], dtype=kw["dtype"],
            callback=kw["callback"], device=kw["device"], blocksize=kw["blocksize"],
        ),
    )
    await stream.start()
    # Pre-fill the queue to maxsize via the same code path
    for i in range(64):
        stream._on_block(bytes([i % 256] * 320), 160, None, None)
    # One more — must drop oldest, not crash
    stream._on_block(b"\xff" * 320, 160, None, None)
    # Drain a few microsecs for call_soon_threadsafe to land
    await asyncio.sleep(0.05)
    # Queue is still at maxsize (drop-oldest), and contains the latest entry
    assert stream._queue.qsize() == 64
    last = None
    while not stream._queue.empty():
        last = stream._queue.get_nowait()
    assert last == b"\xff" * 320
    await stream.stop()


@pytest.mark.asyncio
async def test_output_stream_write_after_stop_raises():
    """Concurrent stop while write is acquiring the lock must yield a clean error."""
    written: list[bytes] = []

    class FakeSDOutput:
        def __init__(self, **kw): pass
        def start(self): pass
        def stop(self): pass
        def close(self): pass
        def write(self, chunk): written.append(bytes(chunk))

    stream = OutputStream(device_index=1, samplerate=16000, _factory=lambda **kw: FakeSDOutput(**kw))
    await stream.start()
    await stream.stop()
    with pytest.raises(RuntimeError, match="not started"):
        await stream.write(b"\x00" * 320)
