from __future__ import annotations


def parse_doctor_output(out: dict, expected: list[str]) -> dict:
    """Compare observed joints against expected; joints missing from `out` are latched."""
    joints = set(out.get("joints", []))
    latched = [j for j in expected if j not in joints]
    return {"bus": out.get("bus", "unknown"), "latched": latched}
