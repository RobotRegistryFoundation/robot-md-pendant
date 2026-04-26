import pytest
from pendantd.mcp_server.server import build_tools


class StubIPC:
    def __init__(self, mapping): self._map = mapping
    async def call(self, method, params=None):
        if method not in self._map:
            raise RuntimeError(f"unknown method: {method!r}")
        return self._map[method]


@pytest.mark.asyncio
async def test_audio_list_devices_tool():
    ipc = StubIPC({"audio.list_devices": {"inputs": [{"name": "Jabra"}], "outputs": []}})
    tools = build_tools(ipc)
    out = await tools["audio.list_devices"]({})
    assert out["inputs"] == [{"name": "Jabra"}]


@pytest.mark.asyncio
async def test_audio_set_input_passes_substring():
    seen = {}
    class IPC:
        async def call(self, method, params=None):
            seen["m"] = method; seen["p"] = params
            return {"matched": {"name": "Jabra"}, "persisted": True}
    tools = build_tools(IPC())
    out = await tools["audio.set_input"]({"name_substring": "Jab"})
    assert seen == {"m": "audio.set_input", "p": {"substring": "Jab"}}
    assert out == {"matched": {"name": "Jabra"}, "persisted": True}


@pytest.mark.asyncio
async def test_voice_status_returns_state():
    ipc = StubIPC({"voice.status": {"state": "listening", "vocabulary": ["claude", "bob"]}})
    tools = build_tools(ipc)
    out = await tools["voice.status"]({})
    assert out["state"] == "listening"
    assert "claude" in out["vocabulary"]


@pytest.mark.asyncio
async def test_tool_surfaces_ipc_error():
    class IPC:
        async def call(self, *a, **kw):
            raise ConnectionError("pendantd not running")
    tools = build_tools(IPC())
    with pytest.raises(ConnectionError):
        await tools["audio.get_active"]({})
