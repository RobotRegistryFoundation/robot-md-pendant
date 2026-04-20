from pendantd.robot_status import parse_doctor_output


def test_parse_ok():
    out = {"bus": "ok", "joints": ["shoulder_pan", "wrist_flex"]}
    assert parse_doctor_output(out, expected=["shoulder_pan", "wrist_flex"]) == {"bus": "ok", "latched": []}


def test_parse_detects_latched():
    out = {"bus": "ok", "joints": ["shoulder_pan"]}
    assert parse_doctor_output(out, expected=["shoulder_pan", "wrist_flex"]) == {"bus": "ok", "latched": ["wrist_flex"]}
