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
