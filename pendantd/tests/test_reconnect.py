import asyncio, json, sys
from pathlib import Path
import pytest, websockets
from pendantd.server import Server
from pendantd.mcp_bridge import MCPBridge
from pendantd.session import Session

MOCK = str(Path(__file__).parent / "fixtures" / "mcp_mock.py")

@pytest.mark.asyncio
async def test_reconnect_clears_estop():
    bridge = MCPBridge(command=[sys.executable, MOCK])
    await bridge.start()
    try:
        server = Server(host="127.0.0.1", port=0, mcp=bridge)
        # Seed: session exists with estopped=True
        server.sessions["t"] = Session(pendant_id="t", estopped=True)
        async with server.run() as addr:
            async with websockets.connect(f"ws://{addr}?id=t") as ws:
                await ws.recv()  # hello
        assert server.sessions["t"].estopped is False
    finally:
        await bridge.stop()
