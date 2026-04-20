from __future__ import annotations
import asyncio
import contextlib
import json
from typing import Any, AsyncIterator, Callable, Optional
from urllib.parse import urlparse, parse_qs

import websockets

from .session import Session
from .watchdog import Watchdog


class Server:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765, mcp=None, buttons: Optional[list] = None, agent_factory: Optional[Callable[[str], Any]] = None) -> None:
        self._host, self._port = host, port
        self.sessions: dict[str, Session] = {}
        self._mcp = mcp
        self._buttons = buttons or []
        self._agent_factory = agent_factory

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[str]:
        async with websockets.serve(self._handle, self._host, self._port) as s:
            sock = next(iter(s.sockets))
            host, port = sock.getsockname()[:2]
            yield f"{host}:{port}"

    async def _handle(self, ws) -> None:
        path = getattr(getattr(ws, "request", None), "path", None) or getattr(ws, "path", "")
        pendant_id = self._extract_id(path)
        session = self.sessions.get(pendant_id)
        if session is None:
            session = Session(pendant_id=pendant_id, buttons=list(self._buttons))
            self.sessions[pendant_id] = session
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
                if not isinstance(msg, dict):
                    continue
                await self._dispatch(ws, session, wd, msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            await wd.stop()

    async def _dispatch(self, ws, session: Session, wd: Watchdog, msg: dict) -> None:
        t = msg.get("type")
        if t == "heartbeat":
            wd.ping()
        elif t == "button_press":
            await self._handle_button(ws, session, msg)

    async def _handle_button(self, ws, session: Session, msg: dict) -> None:
        try:
            idx = int(msg["id"])
        except (KeyError, ValueError, TypeError):
            return
        if idx < 0 or idx >= len(session.buttons):
            return
        btn = session.buttons[idx]
        if btn.get("type") == "prompt":
            await self._run_prompt(ws, session, btn.get("prompt", ""))
            return
        if btn.get("type") == "direct_mcp" and self._mcp is not None:
            tool = btn["tool"]
            args = btn.get("args", {})
            await ws.send(json.dumps({
                "v": 1, "type": "tool_call", "name": tool, "args": args, "status": "start"
            }))
            try:
                result = await self._mcp.call_tool(tool, args)
                is_err = bool(result.get("isError", False))
                summary = (result.get("content") or [{}])[0].get("text", "")
                await ws.send(json.dumps({
                    "v": 1, "type": "tool_call", "name": tool, "args": args,
                    "status": "error" if is_err else "ok", "summary": summary,
                }))
            except Exception as e:
                await ws.send(json.dumps({
                    "v": 1, "type": "tool_call", "name": tool, "args": args,
                    "status": "error", "summary": str(e),
                }))

    async def _run_prompt(self, ws, session, prompt: str):
        from .agent import ToolCallEvent, MessageEvent
        if not self._agent_factory:
            return
        agent = self._agent_factory(session.pendant_id)
        async for ev in agent.run_turn(prompt):
            if isinstance(ev, ToolCallEvent):
                await ws.send(json.dumps({"v": 1, "type": "tool_call", "name": ev.name, "args": ev.args, "status": ev.status, "summary": ev.summary}))
            elif isinstance(ev, MessageEvent):
                await ws.send(json.dumps({"v": 1, "type": "chat_message", "role": ev.role, "text": ev.text}))

    @staticmethod
    def _extract_id(path: str) -> str:
        q = parse_qs(urlparse(path).query)
        ids = q.get("id", ["unknown"])
        return ids[0]
