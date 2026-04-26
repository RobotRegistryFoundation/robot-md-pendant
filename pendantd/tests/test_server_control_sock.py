import asyncio
import json
import os
import tempfile
import pytest
from pendantd.server import ControlSocketServer


@pytest.mark.asyncio
async def test_control_socket_dispatches_to_handler(tmp_path):
    sock = tmp_path / "control.sock"
    handlers = {"ping": lambda params: {"pong": True, "echo": params}}
    srv = ControlSocketServer(path=str(sock), handlers=handlers)
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write((json.dumps({"id": 1, "method": "ping", "params": {"x": 7}}) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        msg = json.loads(line)
        assert msg == {"id": 1, "result": {"pong": True, "echo": {"x": 7}}}
        writer.close()
    finally:
        await srv.stop()


@pytest.mark.asyncio
async def test_control_socket_returns_error_on_unknown_method(tmp_path):
    sock = tmp_path / "control.sock"
    srv = ControlSocketServer(path=str(sock), handlers={})
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write((json.dumps({"id": 1, "method": "missing"}) + "\n").encode())
        await writer.drain()
        msg = json.loads(await reader.readline())
        assert msg["id"] == 1
        assert "error" in msg
        assert msg["error"]["message"].startswith("unknown method")
        writer.close()
    finally:
        await srv.stop()
