import asyncio
import pytest
from pendantd.watchdog import Watchdog


@pytest.mark.asyncio
async def test_watchdog_fires_on_missed_beats():
    fired = asyncio.Event()
    wd = Watchdog(timeout_ms=150, on_lost=lambda: fired.set())
    await wd.start()
    await asyncio.wait_for(fired.wait(), timeout=0.5)
    await wd.stop()


@pytest.mark.asyncio
async def test_watchdog_reset_prevents_fire():
    fired = asyncio.Event()
    wd = Watchdog(timeout_ms=150, on_lost=lambda: fired.set())
    await wd.start()
    for _ in range(5):
        await asyncio.sleep(0.05)
        wd.ping()
    await wd.stop()
    assert not fired.is_set()
