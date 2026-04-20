from __future__ import annotations
import asyncio
import contextlib
import json
from typing import AsyncIterator

import websockets

from .session import Session


class Server:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._host, self._port = host, port

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[str]:
        async with websockets.serve(self._handle, self._host, self._port) as s:
            sock = next(iter(s.sockets))
            host, port = sock.getsockname()[:2]
            yield f"{host}:{port}"

    async def _handle(self, ws: websockets.ServerConnection) -> None:
        session = Session()
        await ws.send(json.dumps(session.hello_payload()))
        try:
            async for _ in ws:
                pass  # further handling in later tasks
        except websockets.ConnectionClosed:
            pass
