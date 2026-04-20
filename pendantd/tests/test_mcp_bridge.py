import pytest, sys
from pathlib import Path
from pendantd.mcp_bridge import MCPBridge

MOCK = str(Path(__file__).parent / "fixtures" / "mcp_mock.py")

@pytest.mark.asyncio
async def test_mcp_bridge_initializes_and_lists_tools():
    bridge = MCPBridge(command=[sys.executable, MOCK])
    await bridge.start()
    try:
        tools = await bridge.list_tools()
        assert {"execute_capability", "estop"} <= {t["name"] for t in tools}
    finally:
        await bridge.stop()

@pytest.mark.asyncio
async def test_mcp_bridge_calls_tool():
    bridge = MCPBridge(command=[sys.executable, MOCK])
    await bridge.start()
    try:
        result = await bridge.call_tool("execute_capability", {"capability": "pick"})
        assert "pick:done" in result["content"][0]["text"]
    finally:
        await bridge.stop()
