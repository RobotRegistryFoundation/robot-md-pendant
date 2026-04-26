import asyncio
import logging
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


@pytest.mark.asyncio
async def test_watcher_logs_callback_exception(caplog):
    """If on_change raises, the exception is logged, not silently swallowed."""
    async def boom(reason: str):
        raise ValueError(f"boom on {reason}")
    w = DeviceWatcher(on_change=boom, debounce_ms=50, _start_udev=False)
    with caplog.at_level(logging.ERROR, logger="pendantd.audio.watcher"):
        w._emit("usb-add")
        await asyncio.sleep(0.2)
    assert any("on_change callback failed" in rec.message for rec in caplog.records)
    assert any("boom on usb-add" in str(rec.exc_info[1]) for rec in caplog.records if rec.exc_info)


def test_watcher_requires_running_loop():
    """Constructing outside a running loop should raise (no get_event_loop fallback)."""
    async def _boom(_): pass
    with pytest.raises(RuntimeError):
        DeviceWatcher(on_change=_boom, _start_udev=False)
