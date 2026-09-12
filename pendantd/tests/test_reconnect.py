import asyncio, json, sys
from pathlib import Path
import pytest, websockets
from pendantd.server import Server
from pendantd.mcp_bridge import MCPBridge
from pendantd.session import Session
from pendantd.protocol import validate

MOCK = str(Path(__file__).parent / "fixtures" / "mcp_mock.py")


@pytest.mark.asyncio
async def test_reconnect_does_not_clear_latch():
    """A socket reconnect is not a human decision: the latch survives it."""
    bridge = MCPBridge(command=[sys.executable, MOCK])
    await bridge.start()
    try:
        server = Server(host="127.0.0.1", port=0, mcp=bridge)
        # Seed: session exists with a confirmed robot-side stop latched
        server.sessions["t"] = Session(pendant_id="t", estopped=True, stop_confirmed=True)
        async with server.run() as addr:
            async with websockets.connect(f"ws://{addr}?id=t") as ws:
                await ws.recv()  # hello
        assert server.sessions["t"].estopped is True
        assert server.sessions["t"].stop_confirmed is True
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_stop_clear_requires_explicit_confirmation():
    bridge = MCPBridge(command=[sys.executable, MOCK])
    await bridge.start()
    try:
        server = Server(host="127.0.0.1", port=0, mcp=bridge)
        server.sessions["t"] = Session(pendant_id="t", estopped=True, stop_confirmed=True)
        async with server.run() as addr:
            async with websockets.connect(f"ws://{addr}?id=t") as ws:
                await ws.recv()  # hello
                await ws.send(json.dumps({"v": 1, "type": "stop_clear"}))
                status = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
                assert status["stop"] == "clear_not_confirmed"
                assert status["reason"] == "explicit_confirmation_required"
                assert status["estopped"] is True
                assert server.sessions["t"].estopped is True

                await ws.send(json.dumps({"v": 1, "type": "stop_clear", "confirm": True}))
                status = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
                assert status["stop"] == "cleared"
                assert status["estopped"] is False
        assert server.sessions["t"].estopped is False
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_stop_clear_keeps_latch_when_the_robot_does_not_confirm():
    class _NoClearMCP:
        async def list_tools(self) -> list[dict]:
            return [{"name": "estop"}]

        async def call_tool(self, name: str, args: dict) -> dict:
            raise AssertionError(f"pendant called unregistered tool {name!r}")

    server = Server(host="127.0.0.1", port=0, mcp=_NoClearMCP())
    server.sessions["t"] = Session(pendant_id="t", estopped=True, stop_confirmed=True)
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=t") as ws:
            await ws.recv()  # hello
            await ws.send(json.dumps({"v": 1, "type": "stop_clear", "confirm": True}))
            status = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
    assert status["stop"] == "clear_not_confirmed"
    assert status["reason"] == "estop_clear_tool_not_registered"
    validate(status)
    assert status["estopped"] is True
    assert server.sessions["t"].estopped is True
