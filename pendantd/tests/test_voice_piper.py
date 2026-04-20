import pytest
from pendantd.voice.piper import Piper


@pytest.mark.asyncio
async def test_piper_streams_pcm_chunks():
    # Fake piper: drain stdin, emit known bytes on stdout
    p = Piper(command=["bash", "-c", "cat > /dev/null; printf 'ABCDEFGH'"])
    chunks = [c async for c in p.synthesize("hello")]
    assert b"".join(chunks) == b"ABCDEFGH"
