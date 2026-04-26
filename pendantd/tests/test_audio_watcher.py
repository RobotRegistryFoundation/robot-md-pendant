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
    """_emit with a longer delay_s fires measurably later than the default debounce."""
    fired_times: list[tuple[str, float]] = []
    loop = asyncio.get_running_loop()

    async def on_change(reason: str):
        fired_times.append((reason, loop.time()))

    # Use debounce=50ms and bluez_grace=300ms so the difference is measurable
    # without relying on real hardware.
    w = DeviceWatcher(
        on_change=on_change,
        debounce_ms=50,
        bluez_grace_ms=300,
        _start_udev=False,
    )
    t0 = loop.time()
    w._emit("usb-add")
    w._emit("bluez-add", delay_s=w._bluez_grace_s)
    await asyncio.sleep(0.5)

    times = dict(fired_times)
    assert set(times) == {"usb-add", "bluez-add"}
    # Normal debounce fires quickly (within 200ms); grace fires after ≥250ms
    assert times["usb-add"] - t0 < 0.2, "normal debounce took too long"
    assert times["bluez-add"] - t0 >= 0.25, "bluez grace delay not applied"
