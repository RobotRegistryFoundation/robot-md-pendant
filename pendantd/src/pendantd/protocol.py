from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas" / "v1"

class ProtocolError(ValueError):
    pass

@lru_cache(maxsize=None)
def _load_schema(msg_type: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / f"{msg_type}.schema.json"
    if not path.exists():
        raise ProtocolError(f"unknown type: {msg_type}")
    return json.loads(path.read_text())

def validate(msg: dict[str, Any]) -> None:
    """Validate a JSON message against its v1 schema. Raises ProtocolError on failure."""
    if not isinstance(msg, dict):
        raise ProtocolError("message must be an object")
    msg_type = msg.get("type")
    if not isinstance(msg_type, str):
        raise ProtocolError("message missing 'type' field")
    schema = _load_schema(msg_type)
    try:
        jsonschema.validate(msg, schema)
    except jsonschema.ValidationError as e:
        raise ProtocolError(f"{msg_type}: {e.message}") from e
