import wave
from pathlib import Path
import pytest

from pendantd.voice.wake import StreamingWakeMatcher


FIX = Path(__file__).parent / "fixtures" / "audio"


def _read_wav_bytes(name: str) -> bytes:
    path = FIX / name
    if not path.exists() or path.stat().st_size < 100:
        return b""
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


class FakeWhisper:
    """Stand-in for faster-whisper: maps PCM identity → fake transcript."""
    def __init__(self, mapping: dict[bytes, str]):
        self._map = mapping

    def transcribe(self, pcm: bytes, **kw):
        text = self._map.get(pcm[:64], "")
        # mimic faster-whisper's segments iterator API
        return ([type("Seg", (), {"text": text})()], None)


def test_matcher_fires_on_robot_name():
    pcm = b"BOB_PCM" + b"\x00" * 200
    fw = FakeWhisper({pcm[:64]: " bob"})
    m = StreamingWakeMatcher(model=fw, vocabulary=["claude", "bob"])
    hits = m.feed(pcm)
    assert hits == [{"phrase": "bob", "transcript": "bob"}]


def test_matcher_fires_on_claude_case_insensitive():
    pcm = b"CL_PCM" + b"\x00" * 200
    fw = FakeWhisper({pcm[:64]: "Claude!"})
    m = StreamingWakeMatcher(model=fw, vocabulary=["claude", "bob"])
    hits = m.feed(pcm)
    assert hits and hits[0]["phrase"] == "claude"


def test_matcher_no_fire_on_silence():
    pcm = b"\x00" * 1024
    fw = FakeWhisper({pcm[:64]: ""})
    m = StreamingWakeMatcher(model=fw, vocabulary=["claude", "bob"])
    assert m.feed(pcm) == []


def test_matcher_fuzzy_edge_match_for_long_names():
    pcm = b"FUZZY" + b"\x00" * 200
    fw = FakeWhisper({pcm[:64]: " rosie"})
    m = StreamingWakeMatcher(model=fw, vocabulary=["claude", "rose"])
    # "rose" is 4 chars → Levenshtein ≤ 1 tolerated → "rosie" matches
    hits = m.feed(pcm)
    assert hits and hits[0]["phrase"] == "rose"


def test_matcher_with_real_recordings_for_claude():
    pcm = _read_wav_bytes("claude_16k.wav")
    if not pcm:
        pytest.skip("piper-generated fixture missing; skip integration assertion")
    from faster_whisper import WhisperModel
    model = WhisperModel("tiny.en", compute_type="int8")
    m = StreamingWakeMatcher(model=model, vocabulary=["claude", "bob"])
    assert any(h["phrase"] == "claude" for h in m.feed(pcm))
