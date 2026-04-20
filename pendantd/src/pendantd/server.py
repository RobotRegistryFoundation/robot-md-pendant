from __future__ import annotations
import asyncio
import contextlib
import json
from typing import AsyncIterator
from urllib.parse import urlparse, parse_qs

import websockets

from .session import Session
from .watchdog import Watchdog


class Server:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._host, self._port = host, port
        self.sessions: dict[str, Session] = {}

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[str]:
        async with websockets.serve(self._handle, self._host, self._port) as s:
            sock = next(iter(s.sockets))
            host, port = sock.getsockname()[:2]
            yield f"{host}:{port}"

    async def _handle(self, ws) -> None:
        path = getattr(getattr(ws, "request", None), "path", None) or getattr(ws, "path", "")
        pendant_id = self._extract_id(path)
        session = self.sessions.setdefault(pendant_id, Session(pendant_id=pendant_id))
        await ws.send(json.dumps(session.hello_payload()))

        def _mark_estopped() -> None:
            session.estopped = True

        wd = Watchdog(timeout_ms=300, on_lost=_mark_estopped)
        await wd.start()
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "heartbeat":
                    wd.ping()
        except websockets.ConnectionClosed:
            pass
        finally:
            await wd.stop()

    @staticmethod
    def _extract_id(path: str) -> str:
        q = parse_qs(urlparse(path).query)
        ids = q.get("id", ["unknown"])
        return ids[0]
