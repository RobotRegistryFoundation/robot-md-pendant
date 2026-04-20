import pytest
from pendantd.protocol import validate, ProtocolError

def test_validate_accepts_valid_heartbeat():
    validate({"v": 1, "type": "heartbeat", "seq": 7})

def test_validate_rejects_unknown_type():
    with pytest.raises(ProtocolError, match="unknown type"):
        validate({"v": 1, "type": "bogus"})

def test_validate_rejects_bad_shape():
    with pytest.raises(ProtocolError):
        validate({"v": 1, "type": "heartbeat", "seq": "oops"})

ALL_TYPES = [
    "hello", "heartbeat", "error",
    "button_press", "chat_prompt", "chat_message", "tool_call",
    "status", "soft_stop", "thumbnail",
    "voice_state", "wake_enabled", "barge_in", "voice_error",
]

def test_every_type_loads():
    from pendantd.protocol import _load_schema
    for t in ALL_TYPES:
        schema = _load_schema(t)
        assert schema["title"] == t
