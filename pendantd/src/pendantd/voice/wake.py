from __future__ import annotations


class WakeDetector:
    def __init__(self, model, name: str, threshold: float = 0.5) -> None:
        self._model = model
        self._name = name
        self._threshold = threshold

    def feed(self, pcm: bytes) -> bool:
        scores = self._model.predict(pcm)
        return scores.get(self._name, 0.0) >= self._threshold
