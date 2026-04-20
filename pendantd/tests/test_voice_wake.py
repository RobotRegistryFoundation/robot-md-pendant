from pendantd.voice.wake import WakeDetector


class FakeModel:
    def __init__(self):
        self._count = 0

    def predict(self, pcm):
        self._count += 1
        return {"claude": 0.95 if self._count > 3 else 0.1}


def test_wake_fires_when_score_above_threshold():
    det = WakeDetector(model=FakeModel(), name="claude", threshold=0.5)
    fires = [det.feed(b"\x00" * 1280) for _ in range(4)]
    assert fires == [False, False, False, True]
