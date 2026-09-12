"""Handshake auth: ?id= is a routing label, the token is the credential."""
import asyncio
import json
import pytest
import websockets
from websockets.exceptions import InvalidStatus

from pendantd.server import Server

TOKEN = "s3cret-token"


@pytest.mark.asyncio
async def test_handshake_without_token_is_closed():
    server = Server(host="127.0.0.1", port=0, token=TOKEN)
    async with server.run() as addr:
        with pytest.raises(InvalidStatus) as exc:
            async with websockets.connect(f"ws://{addr}?id=t"):
                pass
    assert exc.value.response.status_code == 401
    assert server.sessions == {}


@pytest.mark.asyncio
async def test_handshake_with_wrong_token_is_closed():
    server = Server(host="127.0.0.1", port=0, token=TOKEN)
    async with server.run() as addr:
        with pytest.raises(InvalidStatus) as exc:
            async with websockets.connect(f"ws://{addr}?id=t&token=nope"):
                pass
    assert exc.value.response.status_code == 401
    assert server.sessions == {}


@pytest.mark.asyncio
async def test_handshake_with_query_token_is_accepted():
    server = Server(host="127.0.0.1", port=0, token=TOKEN)
    async with server.run() as addr:
        async with websockets.connect(f"ws://{addr}?id=t&token={TOKEN}") as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
    assert msg["type"] == "hello"
    assert "t" in server.sessions


@pytest.mark.asyncio
async def test_handshake_with_bearer_header_is_accepted():
    server = Server(host="127.0.0.1", port=0, token=TOKEN)
    async with server.run() as addr:
        async with websockets.connect(
            f"ws://{addr}?id=t", additional_headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
    assert msg["type"] == "hello"


def test_default_bind_is_loopback():
    """The default listener is not reachable from the LAN; --serve-lan opts in."""
    from pendantd.__main__ import DEFAULT_HOST, LAN_HOST, parse_args

    assert Server()._host == "127.0.0.1"
    assert DEFAULT_HOST == "127.0.0.1"
    assert parse_args([]).serve_lan is False
    assert parse_args(["--serve-lan"]).serve_lan is True
    assert LAN_HOST == "0.0.0.0"


def test_lan_serving_generates_a_token(tmp_path, monkeypatch):
    from pendantd.__main__ import load_or_create_token

    monkeypatch.delenv("PENDANTD_TOKEN", raising=False)
    token = load_or_create_token(tmp_path)
    assert token and (tmp_path / "token").read_text().strip() == token
    assert oct((tmp_path / "token").stat().st_mode)[-3:] == "600"
    assert load_or_create_token(tmp_path) == token  # stable across restarts
