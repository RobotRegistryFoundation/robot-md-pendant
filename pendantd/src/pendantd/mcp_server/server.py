"""pendant-mcp tool surface. Built on top of an IPCClient."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, Tool, TextContent


Tool_ = Callable[[dict], Awaitable[dict]]


def build_tools(ipc: Any) -> dict[str, Tool_]:
    async def _list_devices(p): return await ipc.call("audio.list_devices")
    async def _get_active(p): return await ipc.call("audio.get_active")
    async def _set_input(p):
        return await ipc.call("audio.set_input", {"substring": p.get("name_substring")})
    async def _set_output(p):
        return await ipc.call("audio.set_output", {"substring": p.get("name_substring")})
    async def _test_loopback(p):
        return await ipc.call("audio.test_loopback", {"seconds": p.get("seconds", 2)})
    async def _test_tts(p):
        return await ipc.call("audio.test_tts", {"text": p.get("text", "hello")})
    async def _voice_start(p): return await ipc.call("voice.start")
    async def _voice_stop(p): return await ipc.call("voice.stop")
    async def _voice_status(p): return await ipc.call("voice.status")
    async def _set_aliases(p):
        return await ipc.call("voice.set_wake_aliases", {"aliases": p.get("aliases", [])})
    async def _test_wake(p):
        return await ipc.call("voice.test_wake", {"timeout_seconds": p.get("timeout_seconds", 10)})

    return {
        "audio.list_devices": _list_devices,
        "audio.get_active": _get_active,
        "audio.set_input": _set_input,
        "audio.set_output": _set_output,
        "audio.test_loopback": _test_loopback,
        "audio.test_tts": _test_tts,
        "voice.start": _voice_start,
        "voice.stop": _voice_stop,
        "voice.status": _voice_status,
        "voice.set_wake_aliases": _set_aliases,
        "voice.test_wake": _test_wake,
    }


TOOL_DEFS: list[Tool] = [
    Tool(name="audio.list_devices", description="List audio inputs/outputs visible to pendantd.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="audio.get_active", description="What input/output is pendantd using right now.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="audio.set_input", description="Pin the input device by substring; null to unpin.",
         inputSchema={"type": "object", "properties": {"name_substring": {"type": ["string", "null"]}}}),
    Tool(name="audio.set_output", description="Pin the output device by substring; null to unpin.",
         inputSchema={"type": "object", "properties": {"name_substring": {"type": ["string", "null"]}}}),
    Tool(name="audio.test_loopback", description="Record and play back through the active devices.",
         inputSchema={"type": "object", "properties": {"seconds": {"type": "number", "default": 2}}}),
    Tool(name="audio.test_tts", description="Speak a phrase through the active output.",
         inputSchema={"type": "object", "properties": {"text": {"type": "string", "default": "hello"}}}),
    Tool(name="voice.start", description="Begin always-on wake matching.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="voice.stop", description="Pause wake matching.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="voice.status", description="State, vocabulary, devices, latency.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="voice.set_wake_aliases", description="Add/remove host-side wake aliases.",
         inputSchema={"type": "object", "properties": {"aliases": {"type": "array", "items": {"type": "string"}}}}),
    Tool(name="voice.test_wake", description="Run a one-shot wake check.",
         inputSchema={"type": "object", "properties": {"timeout_seconds": {"type": "number", "default": 10}}}),
]


def make_server(ipc: Any) -> Server:
    server = Server("pendant-mcp")
    tools = build_tools(ipc)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOL_DEFS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> CallToolResult:
        # Return CallToolResult consistently so the MCP envelope always carries
        # isError=True on failures — agents can detect errors reliably (I2).
        if name not in tools:
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=f"unknown tool: {name}")],
            )
        try:
            result = await tools[name](arguments or {})
        except ConnectionError as e:
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=str(e))],
            )
        except Exception as e:
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=f"error: {e}")],
            )
        import json as _json
        return CallToolResult(
            content=[TextContent(type="text", text=_json.dumps(result))],
        )

    return server


async def serve_stdio(ipc: Any) -> None:
    server = make_server(ipc)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
