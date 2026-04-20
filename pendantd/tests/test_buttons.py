from pathlib import Path
import asyncio
import pytest
from pendantd.buttons import load_buttons, ButtonConfigError, ButtonWatcher

FIX = Path(__file__).parent / "fixtures"

def test_loads_valid_yaml():
    buttons = load_buttons(FIX / "buttons.valid.yaml")
    assert len(buttons) == 2
    assert buttons[0]["label"] == "Home"
    assert buttons[0]["type"] == "prompt"

def test_rejects_bad_type():
    with pytest.raises(ButtonConfigError, match="type"):
        load_buttons(FIX / "buttons.invalid.yaml")

@pytest.mark.asyncio
async def test_filewatch_triggers_on_change(tmp_path):
    cfg = tmp_path / "buttons.yaml"
    cfg.write_text('buttons: [{label: "A", type: "prompt", prompt: "a"}]\n')
    updates = []
    watcher = ButtonWatcher(cfg, on_change=lambda bs: updates.append(bs))
    await watcher.start()
    assert len(updates) == 1
    cfg.write_text('buttons: [{label: "B", type: "prompt", prompt: "b"}]\n')
    for _ in range(30):
        await asyncio.sleep(0.1)
        if len(updates) >= 2:
            break
    await watcher.stop()
    assert len(updates) == 2
    assert updates[-1][0]["label"] == "B"
