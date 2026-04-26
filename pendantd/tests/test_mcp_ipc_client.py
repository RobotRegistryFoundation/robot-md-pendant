import asyncio
import json
import pytest
from pendantd.mcp_server.ipc_client import IPCClient


async def echo_server(path):
    async def handle(reader, writer):
        line = await reader.readline()
        msg = json.loads(line)
        resp = {"id": msg["id"], "result": {"echo": msg.get("params", {})}}
        writer.write((json.dumps(resp) + "\n").encode())
        await writer.drain()
        writer.close()
    server = await asyncio.start_unix_server(handle, path=path)
    return server


@pytest.mark.asyncio
async def test_ipc_client_call_returns_result(tmp_path):
    sock = tmp_path / "s.sock"
    server = await echo_server(str(sock))
    try:
        client = IPCClient(path=str(sock))
        result = await client.call("foo", {"x": 1})
        assert result == {"echo": {"x": 1}}
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ipc_client_raises_when_socket_missing(tmp_path):
    client = IPCClient(path=str(tmp_path / "nope.sock"))
    with pytest.raises(ConnectionError):
        await client.call("foo", {})
