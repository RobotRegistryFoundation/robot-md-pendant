import asyncio
import json
import pytest
import websockets
from pendantd.server import Server


@pytest.mark.asyncio
async def test_hello_on_connect():
    server = Server(host="127.0.0.1", port=0)
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}") as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0))
            assert msg["type"] == "hello"
            assert msg["v"] == 1
            assert "buttons" in msg
            assert "wifi_mode" in msg


@pytest.mark.asyncio
async def test_pendant_id_routed_to_session():
    server = Server(host="127.0.0.1", port=0)
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=abc12345") as ws:
            await ws.recv()  # hello
        # server should record the session
        assert "abc12345" in server.sessions
