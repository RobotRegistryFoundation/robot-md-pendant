import asyncio, json
import pytest, websockets
from pendantd.server import Server

class FakeAgent:
    async def run_turn(self, prompt):
        from pendantd.agent import MessageEvent
        yield MessageEvent(text=f"got: {prompt}")

class FakeWhisper:
    async def transcribe(self, data):
        return "hello robot"

@pytest.mark.asyncio
async def test_ptt_window_transcribes_and_feeds_agent():
    server = Server(host="127.0.0.1", port=0, agent_factory=lambda pid: FakeAgent(), whisper=FakeWhisper())
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=t") as ws:
            await ws.recv()  # hello
            await ws.send(json.dumps({"v": 1, "type": "voice_state", "state": "recording"}))
            await ws.send(b"\x01" + b"\x00" * 1000)
            await ws.send(json.dumps({"v": 1, "type": "voice_state", "state": "idle"}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
            assert reply["type"] == "chat_message"
            assert "hello robot" in reply["text"]
