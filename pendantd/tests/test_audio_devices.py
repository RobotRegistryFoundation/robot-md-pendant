from pendantd.audio.devices import (
    Device,
    DeviceList,
    list_devices,
    pick_default,
    match_substring,
)


FAKE = [
    {"index": 0, "name": "USB PnP Sound Device", "max_input_channels": 1, "max_output_channels": 0,
     "default_samplerate": 48000.0, "hostapi": 0},
    {"index": 1, "name": "Jabra SPEAK 410 USB", "max_input_channels": 1, "max_output_channels": 2,
     "default_samplerate": 16000.0, "hostapi": 0},
    {"index": 2, "name": "bcm2835 Headphones", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 44100.0, "hostapi": 0},
    {"index": 3, "name": "vc4-hdmi", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 48000.0, "hostapi": 0},
]


def test_list_devices_partitions_inputs_and_outputs():
    devs = list_devices(query=lambda: FAKE)
    assert [d.name for d in devs.inputs] == ["USB PnP Sound Device", "Jabra SPEAK 410 USB"]
    assert [d.name for d in devs.outputs] == ["Jabra SPEAK 410 USB", "bcm2835 Headphones", "vc4-hdmi"]


def test_pick_default_input_prefers_usb_over_builtin():
    devs = list_devices(query=lambda: FAKE)
    picked = pick_default(devs.inputs, kind="input")
    assert picked.name == "USB PnP Sound Device"


def test_pick_default_output_prefers_headset_class():
    devs = list_devices(query=lambda: FAKE)
    picked = pick_default(devs.outputs, kind="output")
    # Jabra has both input + output → headset class → wins
    assert picked.name == "Jabra SPEAK 410 USB"


def test_match_substring_returns_first_index_winner_when_ambiguous():
    devs = list_devices(query=lambda: FAKE)
    matched = match_substring(devs.outputs, "USB")
    assert matched.name == "Jabra SPEAK 410 USB"  # first by index


def test_match_substring_returns_none_when_missing():
    devs = list_devices(query=lambda: FAKE)
    assert match_substring(devs.outputs, "Sennheiser") is None


def test_pick_default_returns_none_on_empty_list():
    assert pick_default([], kind="input") is None
