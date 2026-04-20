import pytest
from pendantd.voice.whisper import Whisper


@pytest.mark.asyncio
async def test_transcribes_via_subprocess():
    # Fake whisper: drain stdin, echo known text on stdout
    w = Whisper(command=["bash", "-c", "cat > /dev/null; echo HELLO"])
    text = await w.transcribe(b"\x00" * 1000)
    assert text.strip() == "HELLO"
