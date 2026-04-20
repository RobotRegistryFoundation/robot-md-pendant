import asyncio, json
import pytest, websockets
from pendantd.server import Server

class FakeAgent:
    async def run_turn(self, prompt):
        from pendantd.agent import MessageEvent
        yield MessageEvent(text=f"you said: {prompt}")

@pytest.mark.asyncio
async def test_chat_prompt_gets_chat_message_reply():
    server = Server(host="127.0.0.1", port=0, agent_factory=lambda pid: FakeAgent())
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=t") as ws:
            await ws.recv()
            await ws.send(json.dumps({"v": 1, "type": "chat_prompt", "text": "hello"}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
            assert reply["type"] == "chat_message"
            assert "hello" in reply["text"]
