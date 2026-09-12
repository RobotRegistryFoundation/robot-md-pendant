import asyncio, json, sys
from pathlib import Path
import pytest, websockets
from pendantd.server import Server
from pendantd.mcp_bridge import MCPBridge
from pendantd.protocol import validate

MOCK = str(Path(__file__).parent / "fixtures" / "mcp_mock.py")


class _NoEstopMCP:
    """An MCP server with the tools robot-md-mcp actually registers today."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def list_tools(self) -> list[dict]:
        return [{"name": "validate"}, {"name": "render"}, {"name": "doctor_summary"}]

    async def call_tool(self, name: str, args: dict) -> dict:
        self.calls.append(name)
        raise AssertionError(f"pendant called unregistered tool {name!r}")


class _FailingEstopMCP:
    """Registers estop, but the call blows up (transport dead, server crashed)."""

    async def list_tools(self) -> list[dict]:
        return [{"name": "estop"}]

    async def call_tool(self, name: str, args: dict) -> dict:
        raise TimeoutError("no answer from the robot")


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
                assert status["stop"] == "stopped"
                validate(status)
        assert server.sessions["t"].estopped is True
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_soft_stop_without_estop_tool_reports_stop_not_confirmed():
    """No estop tool registered: say so, never display a stop that did not happen."""
    mcp = _NoEstopMCP()
    server = Server(host="127.0.0.1", port=0, mcp=mcp)
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=t") as ws:
            await ws.recv()  # hello
            await ws.send(json.dumps({"v": 1, "type": "soft_stop"}))
            status = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
    assert status["type"] == "status"
    assert status["stop"] == "stop_not_confirmed"
    assert status["estopped"] is False
    assert status["reason"] == "estop_tool_not_registered"
    validate(status)
    assert mcp.calls == []  # never call a tool the server does not register
    assert server.sessions["t"].estopped is False


@pytest.mark.asyncio
async def test_soft_stop_reports_the_exception_class_when_the_call_fails():
    server = Server(host="127.0.0.1", port=0, mcp=_FailingEstopMCP())
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=t") as ws:
            await ws.recv()  # hello
            await ws.send(json.dumps({"v": 1, "type": "soft_stop"}))
            status = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
    assert status["stop"] == "stop_not_confirmed"
    assert status["estopped"] is False
    assert status["reason"] == "TimeoutError"
    validate(status)
    assert server.sessions["t"].estopped is False
