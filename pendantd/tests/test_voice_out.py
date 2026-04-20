import asyncio, json
import pytest, websockets
from pendantd.server import Server

class FakeAgent:
    async def run_turn(self, prompt):
        from pendantd.agent import MessageEvent
        yield MessageEvent(text="reply")

class FakePiper:
    async def synthesize(self, text):
        yield b"AUDIO_A"
        yield b"AUDIO_B"

@pytest.mark.asyncio
async def test_agent_message_produces_audio_out_frames():
    server = Server(host="127.0.0.1", port=0, agent_factory=lambda pid: FakeAgent(), piper=FakePiper())
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=t") as ws:
            await ws.recv()  # hello
            await ws.send(json.dumps({"v": 1, "type": "chat_prompt", "text": "hi"}))
            msgs = []
            # collect until we have at least one text + at least one binary
            deadline = asyncio.get_event_loop().time() + 2.0
            while asyncio.get_event_loop().time() < deadline:
                try:
                    msgs.append(await asyncio.wait_for(ws.recv(), 0.3))
                except asyncio.TimeoutError:
                    break
            bins = [m for m in msgs if isinstance(m, (bytes, bytearray))]
            assert any(bytes(b)[:1] == b"\x02" for b in bins)
