import pytest
from pendantd.agent import AgentSession, ToolCallEvent, MessageEvent

class FakeSDKClient:
    """Mimics the Claude Agent SDK enough for tests."""
    def __init__(self):
        self.calls = []
    async def run(self, prompt):
        self.calls.append(prompt)
        yield {"type": "tool_use", "name": "execute_capability", "input": {"capability": "home"}}
        yield {"type": "tool_result", "name": "execute_capability", "output": "ok"}
        yield {"type": "message", "role": "assistant", "text": "Homed."}

@pytest.mark.asyncio
async def test_agent_session_yields_events():
    fake = FakeSDKClient()
    sess = AgentSession(sdk_client=fake, system_prompt="test")
    events = [e async for e in sess.run_turn("home the arm")]
    types = [type(e).__name__ for e in events]
    assert types == ["ToolCallEvent", "ToolCallEvent", "MessageEvent"]
    assert events[0].status == "start"
    assert events[1].status == "ok"
    assert events[2].text == "Homed."
