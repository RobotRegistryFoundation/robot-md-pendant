"""Adapter exposing the Claude Agent SDK as VoiceLoop's `agent.query(text) -> str`."""
from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import query as _sdk_query, ClaudeAgentOptions, AssistantMessage, TextBlock

log = logging.getLogger(__name__)


class VoiceAgent:
    """Bridges VoiceLoop's query(text) -> str contract to the Claude Agent SDK.

    Each call opens a fresh SDK query iterator with the configured options
    (system prompt + optional MCP server pointing at robot-md-mcp). All
    AssistantMessage TextBlock texts are concatenated into the returned string.
    ToolUseBlocks are handled internally by the SDK; they are not surfaced in
    the voice reply.
    """

    def __init__(
        self,
        system_prompt: str,
        mcp_servers: dict | None = None,
        allowed_tools: list[str] | None = None,
        max_turns: int | None = None,
    ) -> None:
        # allowed_tools is an allowlist, not a hint: the SDK may only use the
        # tools named here. max_turns bounds a single spoken turn so a confused
        # agent stops rather than looping against the robot.
        self._options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            mcp_servers=mcp_servers or {},
            allowed_tools=list(allowed_tools) if allowed_tools is not None else [],
            max_turns=max_turns,
        )

    async def query(self, text: str) -> str:
        if not text.strip():
            return ""
        parts: list[str] = []
        try:
            async for msg in _sdk_query(prompt=text, options=self._options):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            parts.append(block.text)
        except Exception as e:
            log.exception("VoiceAgent.query failed")
            return f"Sorry, I hit an error: {e.__class__.__name__}."
        return " ".join(p for p in parts if p).strip()
