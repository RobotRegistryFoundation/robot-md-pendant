from pendantd.voice.buffer import AudioBuffer


def test_append_and_drain():
    buf = AudioBuffer()
    buf.append(b"\x01" * 640)
    buf.append(b"\x02" * 640)
    data = buf.drain()
    assert len(data) == 1280
    assert buf.drain() == b""
