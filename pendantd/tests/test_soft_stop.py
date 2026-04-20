import asyncio, json, sys
from pathlib import Path
import pytest, websockets
from pendantd.server import Server
from pendantd.mcp_bridge import MCPBridge

MOCK = str(Path(__file__).parent / "fixtures" / "mcp_mock.py")

@pytest.mark.asyncio
async def test_soft_stop_calls_estop_and_marks_session():
    bridge = MCPBridge(command=[sys.executable, MOCK])
    await bridge.start()
    try:
        server = Server(host="127.0.0.1", port=0, mcp=bridge)
        async with server.run() as addr:
            async with websockets.connect(f"ws://{addr}?id=t") as ws:
                await ws.recv()  # hello
                await ws.send(json.dumps({"v": 1, "type": "soft_stop"}))
                status = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
                assert status["type"] == "status"
                assert status["estopped"] is True
        assert server.sessions["t"].estopped is True
    finally:
        await bridge.stop()
