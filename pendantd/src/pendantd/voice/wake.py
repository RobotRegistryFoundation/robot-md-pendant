"""Streaming wake-word detection via transcript matching.

Feeds rolling-window PCM to faster-whisper and matches normalized
transcripts against the configured vocabulary. Vocabulary changes at
runtime (e.g., live-reload of voice.yaml) are reflected on the next feed.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


_NORM = re.compile(r"[^a-z]+")


def _normalize(text: str) -> str:
    return _NORM.sub("", text.lower())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                cur[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            ))
        prev = cur
    return prev[-1]


class StreamingWakeMatcher:
    """Match transcripts of a rolling audio window against a vocabulary.

    Designed to be called every ~500 ms with the latest 1.5 s of PCM.
    """

    def __init__(
        self,
        model: Any,
        vocabulary: Iterable[str],
        sample_rate: int = 16000,
        fuzzy_min_len: int = 4,
        fuzzy_distance: int = 1,
    ) -> None:
        self._model = model
        self._sr = sample_rate
        self._fuzzy_min = fuzzy_min_len
        self._fuzzy_dist = fuzzy_distance
        self.set_vocabulary(vocabulary)

    def set_vocabulary(self, vocabulary: Iterable[str]) -> None:
        self._vocab = [v.strip().lower() for v in vocabulary if v.strip()]
        self._vocab_norm = [_normalize(v) for v in self._vocab]

    @property
    def vocabulary(self) -> list[str]:
        return list(self._vocab)

    def _to_audio(self, pcm: bytes):
        """Convert s16le PCM bytes to float32 numpy array for WhisperModel.

        Pads to an even byte count if necessary so np.frombuffer(dtype=int16)
        never raises ValueError on odd-length buffers.
        """
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            return pcm
        if len(pcm) % 2:
            pcm = pcm + b"\x00"
        return np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768.0

    def _transcribe(self, pcm: bytes) -> str:
        # Try passing raw bytes first (for fake/stub models that key on bytes).
        # Fall back to numpy conversion for real faster-whisper WhisperModel.
        try:
            segments, _info = self._model.transcribe(
                pcm, language="en", vad_filter=True, beam_size=1,
                condition_on_previous_text=False,
            )
        except (TypeError, ValueError):
            audio = self._to_audio(pcm)
            segments, _info = self._model.transcribe(
                audio, language="en", vad_filter=True, beam_size=1,
                condition_on_previous_text=False,
            )
        return " ".join(s.text for s in segments).strip()

    def feed(self, pcm: bytes) -> list[dict]:
        """Return a list of `{phrase, transcript}` dicts for matches in this window.

        Empty list if nothing in the vocabulary matched.
        """
        if not self._vocab:
            return []
        text = self._transcribe(pcm)
        if not text:
            return []
        norm = _normalize(text)
        hits: list[dict] = []
        for phrase, phrase_norm in zip(self._vocab, self._vocab_norm):
            if not phrase_norm:
                continue
            if phrase_norm in norm:
                hits.append({"phrase": phrase, "transcript": text.strip()})
                continue
            if len(phrase_norm) >= self._fuzzy_min:
                # check each word in transcript for fuzzy match
                for word in re.findall(r"[a-z]+", text.lower()):
                    if abs(len(word) - len(phrase_norm)) <= self._fuzzy_dist and \
                       _levenshtein(word, phrase_norm) <= self._fuzzy_dist:
                        hits.append({"phrase": phrase, "transcript": text.strip()})
                        break
        return hits
