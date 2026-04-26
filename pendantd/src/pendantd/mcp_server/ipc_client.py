"""Async JSON-RPC over Unix socket. One call → one connection."""
from __future__ import annotations

import asyncio
import itertools
import json


class IPCClient:
    def __init__(self, path: str = "/run/pendantd/control.sock") -> None:
        self._path = path
        self._ids = itertools.count(1)

    async def call(self, method: str, params: dict | None = None, timeout: float = 5.0) -> dict:
        try:
            reader, writer = await asyncio.open_unix_connection(self._path)
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise ConnectionError(f"pendantd not running at {self._path}: {e}") from e
        try:
            req = {"id": next(self._ids), "method": method, "params": params or {}}
            writer.write((json.dumps(req) + "\n").encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            msg = json.loads(line)
            if "error" in msg:
                raise RuntimeError(msg["error"].get("message", "ipc error"))
            return msg.get("result", {})
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
