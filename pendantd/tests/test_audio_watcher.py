import asyncio
import pytest
from pendantd.audio.watcher import DeviceWatcher


@pytest.mark.asyncio
async def test_watcher_debounces_burst_events():
    fired: list[str] = []
    async def on_change(reason: str): fired.append(reason)

    w = DeviceWatcher(on_change=on_change, debounce_ms=100, _start_udev=False)
    # 5 events within debounce window → 1 fire
    for _ in range(5):
        w._emit("usb-add")
    await asyncio.sleep(0.2)
    assert fired == ["usb-add"]


@pytest.mark.asyncio
async def test_watcher_pendant_hooks_emit_immediately():
    fired: list[str] = []
    async def on_change(reason: str): fired.append(reason)
    w = DeviceWatcher(on_change=on_change, debounce_ms=100, _start_udev=False)
    w.on_pendant_connect()
    w.on_pendant_disconnect()
    await asyncio.sleep(0.2)
    assert fired == ["pendant-connected", "pendant-disconnected"]
