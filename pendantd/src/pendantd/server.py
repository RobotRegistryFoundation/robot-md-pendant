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
    def __init__(self, host: str = "0.0.0.0", port: int = 8765, mcp=None, buttons: Optional[list] = None, agent_factory: Optional[Callable[[str], Any]] = None, whisper=None, piper=None) -> None:
        self._host, self._port = host, port
        self.sessions: dict[str, Session] = {}
        self._mcp = mcp
        self._buttons = buttons or []
        self._agent_factory = agent_factory
        self._whisper = whisper
        self._piper = piper

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

    async def _handle_soft_stop(self, ws, session: Session) -> None:
        if self._mcp is not None:
            try:
                await self._mcp.call_tool("estop", {})
            except Exception:
                pass
        session.estopped = True
        await ws.send(json.dumps({"v": 1, "type": "status", "robot_status": session.robot_status, "estopped": True}))

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
