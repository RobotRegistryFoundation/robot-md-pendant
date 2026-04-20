import asyncio, json
import pytest, websockets
from pendantd.server import Server

class FakeAgent:
    async def run_turn(self, prompt):
        from pendantd.agent import ToolCallEvent, MessageEvent
        yield ToolCallEvent(name="execute_capability", args={"capability": "home"}, status="start")
        yield ToolCallEvent(name="execute_capability", args={}, status="ok", summary="done")
        yield MessageEvent(text="Homed.")

@pytest.mark.asyncio
async def test_prompt_button_streams_agent_events():
    server = Server(host="127.0.0.1", port=0, agent_factory=lambda pid: FakeAgent(), buttons=[
        {"label": "Home", "type": "prompt", "prompt": "Home the arm"},
    ])
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=t") as ws:
            await ws.recv()  # hello
            await ws.send(json.dumps({"v": 1, "type": "button_press", "id": "0"}))
            msgs = [json.loads(await asyncio.wait_for(ws.recv(), 2.0)) for _ in range(3)]
            assert [m["type"] for m in msgs] == ["tool_call", "tool_call", "chat_message"]
