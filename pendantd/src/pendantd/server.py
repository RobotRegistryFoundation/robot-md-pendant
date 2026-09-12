from __future__ import annotations
import asyncio
import contextlib
import http
import json
import logging
import secrets
from typing import Any, AsyncIterator, Callable, Optional
from urllib.parse import urlparse, parse_qs

import websockets

from .session import Session
from .watchdog import Watchdog

log = logging.getLogger(__name__)

# The MCP tool names the pendant would need for a real stop. Neither is
# registered by robot-md-mcp today (it registers validate/render/doctor_summary),
# so the pendant asks the server what it has before calling anything: a client
# must never call a tool the server does not register, and must never report a
# stop it did not get. When the gateway exposes arm.estop through robot-md-mcp
# these names light up with no further change here.
STOP_TOOL = "estop"
STOP_CLEAR_TOOL = "estop_clear"


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, mcp=None, buttons: Optional[list] = None, agent_factory: Optional[Callable[[str], Any]] = None, whisper=None, piper=None, token: Optional[str] = None) -> None:
        self._host, self._port = host, port
        self.sessions: dict[str, Session] = {}
        self._mcp = mcp
        self._buttons = buttons or []
        self._agent_factory = agent_factory
        self._whisper = whisper
        self._piper = piper
        self._token = token
        self._tool_names: Optional[set[str]] = None
        self.on_pendant_connect: Optional[Callable[[], None]] = None
        self.on_pendant_disconnect: Optional[Callable[[], None]] = None

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[str]:
        async with websockets.serve(
            self._handle, self._host, self._port, process_request=self._process_request
        ) as s:
            sock = next(iter(s.sockets))
            host, port = sock.getsockname()[:2]
            yield f"{host}:{port}"

    # ---- handshake auth -------------------------------------------------
    # The client-supplied ?id= is a routing label, never an identity: anyone on
    # the LAN can pick any id. When a token is configured every handshake must
    # carry it (Authorization: Bearer <t>, or ?token=<t> for clients that cannot
    # set headers); anything else gets 401 and the socket is never accepted.
    # __main__ refuses to serve on a LAN address without one.
    def _process_request(self, connection, request):
        if self._token is None:
            return None
        presented = self._presented_token(request)
        if presented is not None and secrets.compare_digest(presented, self._token):
            return None
        log.warning("rejected pendant handshake: missing or bad token")
        return connection.respond(http.HTTPStatus.UNAUTHORIZED, "unauthorized\n")

    @staticmethod
    def _presented_token(request) -> Optional[str]:
        auth = (getattr(request, "headers", {}) or {}).get("Authorization") or ""
        if auth.startswith("Bearer "):
            return auth[len("Bearer "):].strip()
        q = parse_qs(urlparse(getattr(request, "path", "") or "").query)
        vals = q.get("token")
        return vals[0] if vals else None

    async def _handle(self, ws) -> None:
        path = getattr(getattr(ws, "request", None), "path", None) or getattr(ws, "path", "")
        pendant_id = self._extract_id(path)
        session = self.sessions.get(pendant_id)
        if session is None:
            session = Session(pendant_id=pendant_id, buttons=list(self._buttons))
            self.sessions[pendant_id] = session
        # A latch is NOT cleared by reconnecting. Reconnect is a socket event, not
        # a human decision, and the socket is not proof of who reconnected. Clearing
        # is an explicit `stop_clear` message carrying confirm:true (_handle_stop_clear).
        await ws.send(json.dumps(session.hello_payload()))
        if self.on_pendant_connect is not None:
            try: self.on_pendant_connect()
            except Exception: pass

        def _mark_estopped() -> None:
            session.estopped = True

        wd = Watchdog(timeout_ms=300, on_lost=_mark_estopped)
        await wd.start()
        poll_task = asyncio.create_task(self._poll_robot_status(ws, session))
        from .voice.buffer import AudioBuffer
        buf = AudioBuffer()
        recording = False
        tasks: set[asyncio.Task] = set()
        try:
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    # binary audio frame: 1-byte type tag + payload
                    if recording and raw and raw[0] == 0x01:
                        buf.append(bytes(raw[1:]))
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "voice_state":
                    state = msg.get("state")
                    if state == "recording":
                        recording = True
                    elif state == "idle" and recording:
                        recording = False
                        data = buf.drain()
                        if data and self._whisper is not None:
                            try:
                                text = await self._whisper.transcribe(data)
                                if text.strip():
                                    self._launch(tasks, self._run_prompt(ws, session, text))
                            except Exception:
                                pass
                    continue
                await self._dispatch(ws, session, wd, msg, tasks)
        except websockets.ConnectionClosed:
            pass
        finally:
            if self.on_pendant_disconnect is not None:
                try: self.on_pendant_disconnect()
                except Exception: pass
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
            await wd.stop()
            for t in list(tasks):
                t.cancel()
            for t in list(tasks):
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    def _launch(self, tasks: set, coro) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    async def _dispatch(self, ws, session: Session, wd: Watchdog, msg: dict, tasks: set) -> None:
        t = msg.get("type")
        if t == "barge_in":
            active = session._piper_active
            if active is not None and hasattr(active, "cancel"):
                try:
                    await active.cancel()
                except Exception:
                    pass
            return
        if t == "heartbeat":
            wd.ping()
        elif t == "button_press":
            await self._handle_button(ws, session, msg, tasks)
        elif t == "chat_prompt":
            self._launch(tasks, self._run_prompt(ws, session, msg.get("text", "")))
        elif t == "soft_stop":
            await self._handle_soft_stop(ws, session)
        elif t == "stop_clear":
            await self._handle_stop_clear(ws, session, msg)

    async def _poll_robot_status(self, ws, session):
        """Poll robot-md-mcp every 2s. Detects latched joints (joint dropped from read_positions)."""
        if self._mcp is None:
            return
        import json as _json
        from .robot_status import parse_doctor_output
        while True:
            await asyncio.sleep(2.0)
            try:
                if "expected_joints" not in session.robot_status:
                    rendered = await self._mcp.call_tool("render", {})
                    manifest_text = (rendered.get("content") or [{}])[0].get("text", "{}")
                    manifest = _json.loads(manifest_text) if manifest_text else {}
                    joints = [j.get("name") for j in manifest.get("physics", {}).get("joints", []) if j.get("name")]
                    session.robot_status["expected_joints"] = joints
                result = await self._mcp.call_tool("validate", {})
                result_text = (result.get("content") or [{}])[0].get("text", "{}")
                parsed = parse_doctor_output(_json.loads(result_text), expected=session.robot_status["expected_joints"])
                if parsed["latched"] and session.robot_status.get("servo_latched") != parsed["latched"]:
                    session.robot_status = {**session.robot_status, "servo_latched": parsed["latched"]}
                    await ws.send(_json.dumps({"v": 1, "type": "status", "robot_status": session.robot_status, "estopped": session.estopped}))
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    async def _has_tool(self, name: str) -> bool:
        """True only if the connected MCP server actually registers `name`.

        The tool list is fetched once per server process and cached; a failed
        listing is not cached, so a server that comes up later still gets asked.
        """
        if self._mcp is None:
            return False
        if self._tool_names is None:
            try:
                tools = await self._mcp.list_tools()
            except Exception:
                log.warning("MCP tools/list failed; treating stop tools as unavailable", exc_info=True)
                return False
            self._tool_names = {t.get("name") for t in tools if isinstance(t, dict)}
        return name in self._tool_names

    async def _call_stop_tool(self, name: str) -> tuple[bool, str]:
        """Call a stop tool and report what actually happened.

        Returns (confirmed, reason). `confirmed` is True only when the tool ran
        and did not report an error — never on a swallowed exception, never on a
        tool the server does not register.
        """
        if self._mcp is None:
            return False, "no_mcp_server"
        if not await self._has_tool(name):
            return False, f"{name}_tool_not_registered"
        try:
            result = await self._mcp.call_tool(name, {})
        except Exception as e:
            log.warning("MCP %s call failed", name, exc_info=True)
            return False, e.__class__.__name__
        if not isinstance(result, dict):
            return False, "malformed_tool_result"
        if result.get("isError"):
            return False, "tool_reported_error"
        return True, "ok"

    async def _handle_soft_stop(self, ws, session: Session) -> None:
        """Report the stop that happened, not the stop that was asked for.

        Vocabulary matches the rc_car runtime's /api/stop: an unconfirmed stop is
        `stop_not_confirmed` with `estopped: false` and a reason. The operator
        pressed STOP and deserves to know it did not land — a pendant that shows
        STOPPED when nothing stopped is worse than one that shows nothing.
        """
        confirmed, reason = await self._call_stop_tool(STOP_TOOL)
        if confirmed:
            session.estopped = True
            session.stop_confirmed = True
            payload = {
                "v": 1, "type": "status", "robot_status": session.robot_status,
                "estopped": True, "stop": "stopped",
            }
        else:
            payload = {
                "v": 1, "type": "status", "robot_status": session.robot_status,
                "estopped": session.estopped, "stop": "stop_not_confirmed", "reason": reason,
            }
        await ws.send(json.dumps(payload))

    async def _handle_stop_clear(self, ws, session: Session, msg: dict) -> None:
        """Clear a latch only on an explicit, confirmed human request.

        `{"type":"stop_clear","confirm":true}`. Without confirm:true nothing is
        cleared. If the latch came from a confirmed robot-side stop, the robot
        side must confirm the clear too; a latch the pendant set on its own
        (watchdog) clears locally and says so.
        """
        if msg.get("confirm") is not True:
            await ws.send(json.dumps({
                "v": 1, "type": "status", "robot_status": session.robot_status,
                "estopped": session.estopped, "stop": "clear_not_confirmed",
                "reason": "explicit_confirmation_required",
            }))
            return
        if not session.stop_confirmed:
            session.estopped = False
            await ws.send(json.dumps({
                "v": 1, "type": "status", "robot_status": session.robot_status,
                "estopped": False, "stop": "cleared_local_only",
            }))
            return
        cleared, reason = await self._call_stop_tool(STOP_CLEAR_TOOL)
        if cleared:
            session.estopped = False
            session.stop_confirmed = False
            await ws.send(json.dumps({
                "v": 1, "type": "status", "robot_status": session.robot_status,
                "estopped": False, "stop": "cleared",
            }))
            return
        await ws.send(json.dumps({
            "v": 1, "type": "status", "robot_status": session.robot_status,
            "estopped": True, "stop": "clear_not_confirmed", "reason": reason,
        }))

    async def _handle_button(self, ws, session: Session, msg: dict, tasks: set) -> None:
        try:
            idx = int(msg["id"])
        except (KeyError, ValueError, TypeError):
            return
        if idx < 0 or idx >= len(session.buttons):
            return
        btn = session.buttons[idx]
        if btn.get("type") == "prompt":
            self._launch(tasks, self._run_prompt(ws, session, btn.get("prompt", "")))
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
                if self._piper is not None:
                    session._piper_active = self._piper
                    try:
                        async for chunk in self._piper.synthesize(ev.text):
                            await ws.send(b"\x02" + chunk)
                    except Exception:
                        pass
                    finally:
                        session._piper_active = None

    @staticmethod
    def _extract_id(path: str) -> str:
        q = parse_qs(urlparse(path).query)
        ids = q.get("id", ["unknown"])
        return ids[0]


import asyncio as _asyncio
import json as _json
import os as _os
from pathlib import Path as _Path
from typing import Awaitable as _Awaitable, Callable as _Callable


class ControlSocketServer:
    """Unix-socket JSON-RPC server for pendant-mcp ↔ pendantd IPC."""

    Handler = _Callable[[dict], "object | _Awaitable[object]"]

    def __init__(self, path: str, handlers: dict[str, Handler], mode: int = 0o660) -> None:
        self._path = path
        self._handlers = handlers
        self._mode = mode
        self._server: _asyncio.AbstractServer | None = None

    async def start(self) -> None:
        try:
            _os.unlink(self._path)
        except FileNotFoundError:
            pass
        _Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        # Restrict umask so the socket isn't briefly world-rw between bind() and chmod().
        # The parent dir at /run/pendantd is also 0770 root:pendant (Task 17 tmpfiles.d).
        # NOTE: single-instance is enforced upstream by systemd, not here — restart simply
        # unlinks the stale socket above.
        old_umask = _os.umask(0o077)
        try:
            self._server = await _asyncio.start_unix_server(self._handle, path=self._path)
            _os.chmod(self._path, self._mode)
        finally:
            _os.umask(old_umask)

    async def _handle(self, reader: _asyncio.StreamReader, writer: _asyncio.StreamWriter) -> None:
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    return
                try:
                    msg = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                req_id = msg.get("id")
                method = msg.get("method")
                params = msg.get("params", {}) or {}
                if method not in self._handlers:
                    resp = {"id": req_id, "error": {"message": f"unknown method: {method!r}"}}
                else:
                    try:
                        out = self._handlers[method](params)
                        if hasattr(out, "__await__"):
                            out = await out  # type: ignore[assignment]
                        resp = {"id": req_id, "result": out}
                    except Exception as e:  # surface failures, never crash
                        resp = {"id": req_id, "error": {"message": str(e)}}
                writer.write((_json.dumps(resp) + "\n").encode())
                await writer.drain()
        finally:
            try: writer.close()
            except Exception: pass

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            try:
                _os.unlink(self._path)
            except FileNotFoundError:
                pass
