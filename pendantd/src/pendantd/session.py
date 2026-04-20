from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Session:
    pendant_id: str = "unknown"
    buttons: list = field(default_factory=list)
    voice_state: dict = field(default_factory=lambda: {"state": "idle"})
    wifi_mode: str = "sta"
    robot_status: dict = field(default_factory=lambda: {"bus": "ok"})
    estopped: bool = False
    # NEW — reference to the piper currently streaming, if any, for barge-in cancellation
    _piper_active: object | None = None

    def hello_payload(self) -> dict:
        return {
            "v": 1,
            "type": "hello",
            "buttons": self.buttons,
            "voice_state": self.voice_state,
            "wifi_mode": self.wifi_mode,
            "robot_status": self.robot_status,
        }
