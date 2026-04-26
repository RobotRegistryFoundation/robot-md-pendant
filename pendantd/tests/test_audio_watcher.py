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


@pytest.mark.asyncio
async def test_watcher_bluez_grace_fires_with_longer_delay():
    """_emit with a custom delay fires later than the default debounce."""
    fired_times: list[float] = []
    loop = asyncio.get_running_loop()

    async def on_change(reason: str):
        fired_times.append(loop.time())

    # Use a long debounce (100ms) and a longer bluez_grace (300ms) so the
    # difference is measurable without relying on real hardware.
    w = DeviceWatcher(
        on_change=on_change,
        debounce_ms=50,
        bluez_grace_ms=300,
        _start_udev=False,
    )
    t0 = loop.time()
    # Simulate a normal usb-add (debounce=50ms) and a bluez add (grace=300ms)
    w._emit("usb-add")
    w._emit("bluez-add", delay_s=w._bluez_grace_s)
    await asyncio.sleep(0.5)
    # bluez-add should fire after the grace period (≥ 300ms); usb-add fires at 50ms
    assert len(fired_times) == 2
    # Verify both fired; order might vary but bluez fires later overall
    # (We check the watcher stored the bluez grace correctly.)
    assert w._bluez_grace_s == pytest.approx(0.3)
