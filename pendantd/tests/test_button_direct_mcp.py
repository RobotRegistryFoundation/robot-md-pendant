import asyncio, json, sys
from pathlib import Path
import pytest, websockets
from pendantd.server import Server
from pendantd.mcp_bridge import MCPBridge

MOCK = str(Path(__file__).parent / "fixtures" / "mcp_mock.py")

@pytest.mark.asyncio
async def test_direct_mcp_button_triggers_tool_call():
    bridge = MCPBridge(command=[sys.executable, MOCK])
    await bridge.start()
    try:
        server = Server(host="127.0.0.1", port=0, mcp=bridge, buttons=[
            {"label": "Estop", "type": "direct_mcp", "tool": "estop", "args": {}},
        ])
        async with server.run() as addr:
            async with websockets.connect(f"ws://{addr}?id=t") as ws:
                await ws.recv()  # hello
                await ws.send(json.dumps({"v": 1, "type": "button_press", "id": "0"}))
                events = []
                for _ in range(2):
                    events.append(json.loads(await asyncio.wait_for(ws.recv(), 2.0)))
                assert events[0]["type"] == "tool_call" and events[0]["status"] == "start"
                assert events[1]["type"] == "tool_call" and events[1]["status"] == "ok"
    finally:
        await bridge.stop()
