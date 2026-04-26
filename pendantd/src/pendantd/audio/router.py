"""AudioRouter — owns active input and output streams, swaps on changes."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from pendantd.audio.devices import Device, DeviceList, match_substring, pick_default


def _default_input_factory(**kw: Any) -> Any:  # pragma: no cover
    from pendantd.audio.streams import InputStream
    return InputStream(**kw)


def _default_output_factory(**kw: Any) -> Any:  # pragma: no cover
    from pendantd.audio.streams import OutputStream
    return OutputStream(**kw)


class AudioRouter:
    def __init__(
        self,
        pinned_input: str = "",
        pinned_output: str = "",
        samplerate: int = 16000,
        _input_factory: Callable[..., Any] = _default_input_factory,
        _output_factory: Callable[..., Any] = _default_output_factory,
    ) -> None:
        self._pin_in = pinned_input
        self._pin_out = pinned_output
        self._sr = samplerate
        self._mk_in = _input_factory
        self._mk_out = _output_factory
        self.active_input: Device | None = None
        self.active_output: Device | None = None
        self._in_stream: Any = None
        self._out_stream: Any = None
        self.last_fallback: str = ""
        self._update_lock = asyncio.Lock()

    def _resolve(self, devs: DeviceList) -> tuple[Device | None, Device | None]:
        in_dev: Device | None = None
        out_dev: Device | None = None
        self.last_fallback = ""

        if self._pin_in:
            in_dev = match_substring(devs.inputs, self._pin_in)
            if in_dev is None:
                fallback = pick_default(devs.inputs, kind="input")
                if fallback is not None:
                    self.last_fallback = (
                        f"input pin {self._pin_in!r} not present; "
                        f"auto-picked {fallback.name!r}"
                    )
                in_dev = fallback
        else:
            in_dev = pick_default(devs.inputs, kind="input")

        if self._pin_out:
            out_dev = match_substring(devs.outputs, self._pin_out)
            if out_dev is None:
                fallback = pick_default(devs.outputs, kind="output", all_devices=devs)
                if fallback is not None:
                    msg = f"output pin {self._pin_out!r} not present; auto-picked {fallback.name!r}"
                    self.last_fallback = (self.last_fallback + "; " + msg).lstrip("; ")
                out_dev = fallback
        else:
            out_dev = pick_default(devs.outputs, kind="output", all_devices=devs)

        return in_dev, out_dev

    async def attach(self, devs: DeviceList) -> None:
        in_dev, out_dev = self._resolve(devs)
        if in_dev is not None:
            self._in_stream = self._mk_in(device_index=in_dev.index, samplerate=self._sr)
            await self._in_stream.start()
            self.active_input = in_dev
        if out_dev is not None:
            self._out_stream = self._mk_out(device_index=out_dev.index, samplerate=self._sr)
            await self._out_stream.start()
            self.active_output = out_dev

    async def update(self, devs: DeviceList) -> None:
        async with self._update_lock:
            new_in, new_out = self._resolve(devs)
            if new_in != self.active_input:
                if self._in_stream is not None:
                    await self._in_stream.stop()
                self._in_stream = None
                if new_in is not None:
                    self._in_stream = self._mk_in(device_index=new_in.index, samplerate=self._sr)
                    await self._in_stream.start()
                self.active_input = new_in
            if new_out != self.active_output:
                if self._out_stream is not None:
                    await self._out_stream.stop()
                self._out_stream = None
                if new_out is not None:
                    self._out_stream = self._mk_out(device_index=new_out.index, samplerate=self._sr)
                    await self._out_stream.start()
                self.active_output = new_out

    async def read(self) -> bytes:
        if self._in_stream is None:
            raise RuntimeError("no active input")
        return await self._in_stream.read()

    async def write(self, chunk: bytes) -> None:
        if self._out_stream is None:
            return  # silently drop if no output
        await self._out_stream.write(chunk)

    async def shutdown(self) -> None:
        if self._in_stream is not None:
            await self._in_stream.stop()
        if self._out_stream is not None:
            await self._out_stream.stop()
        self._in_stream = None
        self._out_stream = None
        self.active_input = None
        self.active_output = None

    @property
    def pin_in(self) -> str:
        return self._pin_in

    @property
    def pin_out(self) -> str:
        return self._pin_out

    def set_pin(self, kind: str, substring: str) -> None:
        if kind == "input":
            self._pin_in = substring
        elif kind == "output":
            self._pin_out = substring
        else:
            raise ValueError(f"unknown kind: {kind!r}")
