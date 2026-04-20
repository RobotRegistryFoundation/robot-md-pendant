from __future__ import annotations
from dataclasses import dataclass, field
from typing import AsyncIterator

@dataclass
class ToolCallEvent:
    name: str
    args: dict = field(default_factory=dict)
    status: str = "start"  # "start" | "ok" | "error"
    summary: str = ""

@dataclass
class MessageEvent:
    text: str
    role: str = "assistant"

class AgentSession:
    """Adapter around an SDK client that yields typed events.

    Maps the SDK's raw dict stream (tool_use / tool_result / message) to
    ToolCallEvent and MessageEvent. The real integration binds
    claude_agent_sdk.ClaudeAgent with MCP servers; that happens at wire time.
    """
    def __init__(self, sdk_client, system_prompt: str) -> None:
        self._sdk = sdk_client
        self._system = system_prompt

    async def run_turn(self, prompt: str) -> AsyncIterator:
        async for item in self._sdk.run(prompt):
            t = item.get("type")
            if t == "tool_use":
                yield ToolCallEvent(name=item["name"], args=item.get("input", {}), status="start")
            elif t == "tool_result":
                yield ToolCallEvent(name=item["name"], args={}, status="ok", summary=str(item.get("output", "")))
            elif t == "message":
                yield MessageEvent(text=item["text"], role=item.get("role", "assistant"))
