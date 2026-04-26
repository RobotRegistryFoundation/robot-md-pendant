"""DeviceWatcher — coalesces USB udev events and pendant connect/disconnect."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable


OnChange = Callable[[str], Awaitable[None]]

log = logging.getLogger(__name__)


class DeviceWatcher:
    """Coalesce hotplug events and emit debounced async callbacks.

    Must be instantiated inside a running asyncio loop. Pendant
    connect/disconnect hooks share the same per-reason debounce as udev
    events. Callback exceptions are logged via stdlib logging.
    """
    def __init__(
        self,
        on_change: OnChange,
        debounce_ms: int = 300,
        _start_udev: bool = True,
    ) -> None:
        self._on_change = on_change
        self._debounce_s = debounce_ms / 1000.0
        self._loop = asyncio.get_running_loop()
        self._pending: dict[str, asyncio.TimerHandle] = {}
        self._udev_task: asyncio.Task | None = None
        if _start_udev:
            self._udev_task = self._loop.create_task(self._run_udev())

    def _emit(self, reason: str) -> None:
        if reason in self._pending:
            self._pending[reason].cancel()
        handle = self._loop.call_later(self._debounce_s, self._fire, reason)
        self._pending[reason] = handle

    def _fire(self, reason: str) -> None:
        self._pending.pop(reason, None)
        task = self._loop.create_task(self._on_change(reason))
        task.add_done_callback(self._log_callback_exception)

    @staticmethod
    def _log_callback_exception(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("DeviceWatcher on_change callback failed: %s", exc, exc_info=exc)

    def on_pendant_connect(self) -> None:
        self._emit("pendant-connected")

    def on_pendant_disconnect(self) -> None:
        self._emit("pendant-disconnected")

    async def _run_udev(self) -> None:  # pragma: no cover - hardware
        try:
            import pyudev
        except ImportError:
            return
        ctx = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(ctx)
        monitor.filter_by(subsystem="sound")
        monitor.start()
        while True:
            device = await self._loop.run_in_executor(None, monitor.poll, 1.0)
            if device is None:
                continue
            action = device.action
            if action in ("add", "remove", "change"):
                self._emit(f"usb-{action}")

    async def stop(self) -> None:
        if self._udev_task is not None:
            self._udev_task.cancel()
            try:
                await self._udev_task
            except asyncio.CancelledError:
                pass
        for handle in list(self._pending.values()):
            handle.cancel()
        self._pending.clear()
