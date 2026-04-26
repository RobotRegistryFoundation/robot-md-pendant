"""Audio device discovery + auto-pick."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

Kind = Literal["input", "output"]


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    channels: int
    sample_rate: int
    kind: Kind

    def matches(self, substring: str) -> bool:
        return substring.lower() in self.name.lower()


@dataclass(frozen=True)
class DeviceList:
    inputs: list[Device]
    outputs: list[Device]


def _query_sd() -> list[dict]:  # pragma: no cover - thin wrapper
    import sounddevice as sd
    return list(sd.query_devices())


def list_devices(query: Callable[[], list[dict]] = _query_sd) -> DeviceList:
    """Enumerate audio devices and partition by kind.

    `query` defaults to `sounddevice.query_devices()`; injectable for tests.
    """
    raw = query()
    inputs: list[Device] = []
    outputs: list[Device] = []
    for d in raw:
        if d.get("max_input_channels", 0) > 0:
            inputs.append(Device(
                index=d["index"], name=d["name"],
                channels=d["max_input_channels"],
                sample_rate=int(d.get("default_samplerate", 16000)),
                kind="input",
            ))
        if d.get("max_output_channels", 0) > 0:
            outputs.append(Device(
                index=d["index"], name=d["name"],
                channels=d["max_output_channels"],
                sample_rate=int(d.get("default_samplerate", 16000)),
                kind="output",
            ))
    return DeviceList(inputs=inputs, outputs=outputs)


def _is_usb(name: str) -> bool:
    n = name.lower()
    return "usb" in n or "jabra" in n or "logitech" in n or "plantronics" in n


def _is_builtin(name: str) -> bool:
    n = name.lower()
    return "bcm2835" in n or "hdmi" in n


def _is_bluetooth(name: str) -> bool:
    n = name.lower()
    return "bluez" in n or "bluetooth" in n or "a2dp" in n


def _is_pendant(name: str) -> bool:
    return name.lower().startswith("pendant:")


def _input_priority(d: Device) -> int:
    # lower = better
    if _is_pendant(d.name):
        return 0
    if _is_usb(d.name):
        return 1
    if _is_bluetooth(d.name):
        return 2
    if _is_builtin(d.name):
        return 4
    return 3


def _output_priority(d: Device, has_input_partner: bool) -> int:
    if _is_pendant(d.name):
        return 0
    if has_input_partner and _is_usb(d.name):
        return 1  # headset class
    if _is_usb(d.name):
        return 2
    if "hdmi" in d.name.lower():
        return 3
    if _is_builtin(d.name):
        return 4
    return 3


def pick_default(devices: list[Device], kind: Kind, all_devices: DeviceList | None = None) -> Device | None:
    """Pick the highest-priority device.

    For outputs, headset-class detection looks for an input device with the same
    name; pass `all_devices` to enable. Defaults to no headset detection (still
    picks USB > HDMI > built-in).
    """
    if not devices:
        return None
    if kind == "input":
        return min(devices, key=lambda d: (_input_priority(d), d.index))
    input_names = {d.name for d in (all_devices.inputs if all_devices else [])}
    return min(
        devices,
        key=lambda d: (_output_priority(d, d.name in input_names), d.index),
    )


def match_substring(devices: list[Device], substring: str) -> Device | None:
    """Case-insensitive substring match. First match by index order wins."""
    if not substring:
        return None
    matches = [d for d in devices if d.matches(substring)]
    if not matches:
        return None
    return min(matches, key=lambda d: d.index)
