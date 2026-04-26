"""Tests for VoiceAgent — the Claude Agent SDK adapter for VoiceLoop."""
import pytest
from unittest.mock import MagicMock

# claude_agent_sdk is a project dependency; skip gracefully if this test runner
# doesn't have it installed (e.g. the system pytest on the Pi without the venv).
claude_agent_sdk = pytest.importorskip("claude_agent_sdk")
AssistantMessage = claude_agent_sdk.AssistantMessage
TextBlock = claude_agent_sdk.TextBlock


def _make_assistant_msg(texts: list[str]) -> MagicMock:
    """Return a MagicMock with spec=AssistantMessage whose .content has TextBlock mocks."""
    msg = MagicMock(spec=AssistantMessage)
    blocks = []
    for t in texts:
        block = MagicMock(spec=TextBlock)
        block.text = t
        blocks.append(block)
    msg.content = blocks
    return msg


@pytest.mark.asyncio
async def test_voice_agent_concatenates_text_blocks(monkeypatch):
    """VoiceAgent.query collects all AssistantMessage TextBlock.text into one reply."""
    msg1 = _make_assistant_msg(["Hello, "])
    msg2 = _make_assistant_msg(["world."])

    async def fake_query(prompt, options=None):
        yield msg1
        yield msg2

    monkeypatch.setattr("pendantd.voice.agent_adapter._sdk_query", fake_query)

    from pendantd.voice.agent_adapter import VoiceAgent
    agent = VoiceAgent(system_prompt="test")
    reply = await agent.query("hi")
    assert "Hello," in reply and "world." in reply


@pytest.mark.asyncio
async def test_voice_agent_handles_empty_text():
    from pendantd.voice.agent_adapter import VoiceAgent
    agent = VoiceAgent(system_prompt="test")
    assert await agent.query("") == ""
    assert await agent.query("   ") == ""


@pytest.mark.asyncio
async def test_voice_agent_swallows_sdk_errors(monkeypatch):
    async def boom_query(prompt, options=None):
        raise RuntimeError("SDK exploded")
        yield  # unreachable; pragma: no cover

    monkeypatch.setattr("pendantd.voice.agent_adapter._sdk_query", boom_query)

    from pendantd.voice.agent_adapter import VoiceAgent
    agent = VoiceAgent(system_prompt="test")
    reply = await agent.query("hi")
    assert "error" in reply.lower()


@pytest.mark.asyncio
async def test_voice_agent_ignores_non_assistant_messages(monkeypatch):
    """Non-AssistantMessage objects (e.g. SystemMessage, ResultMessage) are skipped."""
    non_assistant = MagicMock()  # no AssistantMessage spec — isinstance returns False

    async def fake_query(prompt, options=None):
        yield non_assistant

    monkeypatch.setattr("pendantd.voice.agent_adapter._sdk_query", fake_query)

    from pendantd.voice.agent_adapter import VoiceAgent
    agent = VoiceAgent(system_prompt="test")
    reply = await agent.query("hi")
    assert reply == ""
