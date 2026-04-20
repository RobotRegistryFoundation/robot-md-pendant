import array
from pendantd.voice.endpoint import Endpointer

def pcm_rms(value, n=320):  # 20ms @ 16k mono s16le
    return array.array("h", [value] * n).tobytes()

def test_endpointer_fires_after_silence():
    ended = []
    ep = Endpointer(rms_threshold=100, silence_ms=60, on_end=lambda: ended.append(True))
    ep.feed(pcm_rms(3000))  # voice
    ep.feed(pcm_rms(3000))  # voice
    ep.feed(pcm_rms(0))     # silence 20ms
    ep.feed(pcm_rms(0))     # silence 40ms
    ep.feed(pcm_rms(0))     # silence 60ms — fire
    assert ended == [True]

def test_endpointer_does_not_fire_without_voice():
    ended = []
    ep = Endpointer(rms_threshold=100, silence_ms=60, on_end=lambda: ended.append(True))
    for _ in range(10):
        ep.feed(pcm_rms(0))
    assert ended == []
