import asyncio, json
import pytest, websockets
from pendantd.server import Server

class SlowPiper:
    def __init__(self):
        self.cancelled = False
    async def synthesize(self, text):
        for _ in range(10):
            if self.cancelled:
                return
            await asyncio.sleep(0.05)
            yield b"X" * 100
    async def cancel(self):
        self.cancelled = True

class FakeAgent:
    async def run_turn(self, prompt):
        from pendantd.agent import MessageEvent
        yield MessageEvent(text="reply")

@pytest.mark.asyncio
async def test_barge_in_cancels_piper():
    piper = SlowPiper()
    server = Server(host="127.0.0.1", port=0, agent_factory=lambda pid: FakeAgent(), piper=piper)
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=t") as ws:
            await ws.recv()  # hello
            await ws.send(json.dumps({"v": 1, "type": "chat_prompt", "text": "hi"}))
            # wait a tick for audio to start
            await asyncio.sleep(0.12)
            await ws.send(json.dumps({"v": 1, "type": "barge_in"}))
            await asyncio.sleep(0.3)
    assert piper.cancelled
