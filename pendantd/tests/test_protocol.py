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
