from pathlib import Path
import asyncio
import pytest
from pendantd.voice_cfg import load_voice_cfg, VoiceConfigError, VoiceCfgWatcher

def test_loads_valid(tmp_path):
    cfg = tmp_path / "voice.yaml"
    cfg.write_text("wake_word: false\ntts_voice: 'x'\n")
    out = load_voice_cfg(cfg)
    assert out["wake_word"] is False
    assert out["tts_voice"] == "x"

def test_rejects_missing_required(tmp_path):
    cfg = tmp_path / "voice.yaml"
    cfg.write_text("wake_word: false\n")  # missing tts_voice
    with pytest.raises(VoiceConfigError):
        load_voice_cfg(cfg)

def test_load_voice_cfg_fills_new_defaults_for_old_files(tmp_path):
    p = tmp_path / "voice.yaml"
    p.write_text("wake_word: claude\ntts_voice: en_US-amy-medium\n")
    cfg = load_voice_cfg(p)
    assert cfg["wake_word"] == "claude"
    assert cfg["robot_name"] == ""        # default
    assert cfg["wake_aliases"] == []      # default
    assert cfg["input_device"] == ""      # default
    assert cfg["output_device"] == ""     # default
    assert cfg["sample_rate"] == 16000    # default

@pytest.mark.asyncio
async def test_watcher_triggers_on_change(tmp_path):
    cfg = tmp_path / "voice.yaml"
    cfg.write_text("wake_word: false\ntts_voice: 'a'\n")
    updates = []
    w = VoiceCfgWatcher(cfg, on_change=lambda c: updates.append(c))
    await w.start()
    assert len(updates) == 1
    cfg.write_text("wake_word: true\ntts_voice: 'a'\n")
    for _ in range(30):
        await asyncio.sleep(0.1)
        if len(updates) >= 2: break
    await w.stop()
    assert updates[-1]["wake_word"] is True


# --- v3.3 §8.7 manifest voice block integration ---


_BOB_MANIFEST_WITH_VOICE = """\
---
rcan_version: '3.3'
metadata:
  robot_name: bob
  rrn: RRN-000000000003
voice:
  aliases: [bobby, hey-bob]
  language: en-US
  tts_voice: en_US-amy-low
---

# Bob
"""


_BOB_MANIFEST_NO_VOICE = """\
---
rcan_version: '3.3'
metadata:
  robot_name: bob
  rrn: RRN-000000000003
---

# Bob
"""


def test_load_voice_cfg_pulls_defaults_from_manifest(tmp_path):
    """When manifest_path is provided, voice block fills in defaults
    that the sidecar can override."""
    manifest = tmp_path / "ROBOT.md"
    manifest.write_text(_BOB_MANIFEST_WITH_VOICE)

    sidecar = tmp_path / "voice.yaml"
    sidecar.write_text("wake_word: claude\n")  # no tts_voice in sidecar

    cfg = load_voice_cfg(sidecar, manifest_path=manifest)
    assert cfg["wake_word"] == "claude"
    assert cfg["robot_name"] == "bob"  # from manifest
    assert cfg["wake_aliases"] == ["bobby", "hey-bob"]  # from manifest
    assert cfg["tts_voice"] == "en_US-amy-low"  # from manifest
    assert cfg["language"] == "en-US"  # from manifest (matches default but sourced)


def test_sidecar_overrides_manifest(tmp_path):
    """Sidecar values take precedence over manifest defaults — host customization wins."""
    manifest = tmp_path / "ROBOT.md"
    manifest.write_text(_BOB_MANIFEST_WITH_VOICE)

    sidecar = tmp_path / "voice.yaml"
    sidecar.write_text(
        "wake_word: claude\n"
        "wake_aliases: [host-only-alias]\n"
        "tts_voice: en_US-amy-medium\n"
    )

    cfg = load_voice_cfg(sidecar, manifest_path=manifest)
    assert cfg["wake_aliases"] == ["host-only-alias"]  # sidecar wins
    assert cfg["tts_voice"] == "en_US-amy-medium"  # sidecar wins


def test_manifest_without_voice_block_keeps_sidecar_authoritative(tmp_path):
    """Manifest with no voice block: only robot_name flows through; sidecar
    must still supply tts_voice."""
    manifest = tmp_path / "ROBOT.md"
    manifest.write_text(_BOB_MANIFEST_NO_VOICE)

    sidecar = tmp_path / "voice.yaml"
    sidecar.write_text("wake_word: claude\ntts_voice: en_US-amy-medium\n")

    cfg = load_voice_cfg(sidecar, manifest_path=manifest)
    assert cfg["robot_name"] == "bob"  # from manifest
    assert cfg["wake_aliases"] == []  # default (no manifest voice block)
    assert cfg["tts_voice"] == "en_US-amy-medium"


def test_tts_voice_required_after_merge(tmp_path):
    """Sidecar without tts_voice + manifest without voice block → still errors."""
    manifest = tmp_path / "ROBOT.md"
    manifest.write_text(_BOB_MANIFEST_NO_VOICE)

    sidecar = tmp_path / "voice.yaml"
    sidecar.write_text("wake_word: claude\n")  # no tts_voice anywhere

    with pytest.raises(VoiceConfigError, match="tts_voice"):
        load_voice_cfg(sidecar, manifest_path=manifest)


def test_manifest_path_none_preserves_sidecar_only_behavior(tmp_path):
    """The default (manifest_path=None) keeps the original sidecar-only
    semantics — backward compat."""
    sidecar = tmp_path / "voice.yaml"
    sidecar.write_text("wake_word: claude\ntts_voice: en_US-amy-medium\n")

    cfg = load_voice_cfg(sidecar)  # no manifest_path
    assert cfg["wake_word"] == "claude"
    assert cfg["tts_voice"] == "en_US-amy-medium"
    assert cfg["robot_name"] == ""  # default, no manifest
