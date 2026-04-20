import asyncio, base64
import pytest
from pendantd.vision import ThumbnailProducer

@pytest.mark.asyncio
async def test_producer_emits_thumbnails():
    frames = []
    prod = ThumbnailProducer(grab=lambda: b"fakejpeg", fps=10, on_frame=lambda ev: frames.append(ev))
    await prod.start()
    await asyncio.sleep(0.25)
    await prod.stop()
    assert len(frames) >= 2
    assert frames[0]["type"] == "thumbnail"
    assert base64.b64decode(frames[0]["b64"]) == b"fakejpeg"
