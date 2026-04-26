import asyncio
import pytest
from pendantd.audio.devices import Device, DeviceList
from pendantd.audio.router import AudioRouter


def _dev(idx, name, kind):
    chans = 1 if kind == "input" else 2
    return Device(index=idx, name=name, channels=chans, sample_rate=16000, kind=kind)


class FakeStream:
    def __init__(self, device_index, **_):
        self.device_index = device_index
        self.started = False
        self.stopped = False
        self.written: list[bytes] = []
    async def start(self): self.started = True
    async def read(self):
        await asyncio.sleep(0.01)
        return b"\x00\x00" * 160
    async def write(self, chunk): self.written.append(bytes(chunk))
    async def stop(self): self.stopped = True


@pytest.fixture
def fake_streams():
    inputs: list[FakeStream] = []
    outputs: list[FakeStream] = []
    def make_input(device_index, **kw):
        s = FakeStream(device_index); inputs.append(s); return s
    def make_output(device_index, **kw):
        s = FakeStream(device_index); outputs.append(s); return s
    return inputs, outputs, make_input, make_output


@pytest.mark.asyncio
async def test_router_picks_default_when_unpinned(fake_streams):
    ins, outs, mki, mko = fake_streams
    devs = DeviceList(
        inputs=[_dev(0, "USB PnP Sound Device", "input")],
        outputs=[_dev(0, "Jabra SPEAK 410 USB", "output")],
    )
    r = AudioRouter(_input_factory=mki, _output_factory=mko)
    await r.attach(devs)
    assert r.active_input.name == "USB PnP Sound Device"
    assert r.active_output.name == "Jabra SPEAK 410 USB"
    await r.shutdown()


@pytest.mark.asyncio
async def test_router_swaps_streams_when_devices_change(fake_streams):
    ins, outs, mki, mko = fake_streams
    devs1 = DeviceList(inputs=[_dev(0, "USB PnP Sound Device", "input")], outputs=[])
    r = AudioRouter(_input_factory=mki, _output_factory=mko)
    await r.attach(devs1)
    devs2 = DeviceList(inputs=[_dev(1, "Jabra SPEAK 410 USB", "input")], outputs=[])
    await r.update(devs2)
    assert r.active_input.name == "Jabra SPEAK 410 USB"
    assert ins[0].stopped is True
    await r.shutdown()


@pytest.mark.asyncio
async def test_router_honors_pinned_input_when_present(fake_streams):
    ins, outs, mki, mko = fake_streams
    devs = DeviceList(
        inputs=[_dev(0, "USB PnP Sound Device", "input"),
                _dev(1, "Jabra SPEAK 410 USB", "input")],
        outputs=[],
    )
    r = AudioRouter(_input_factory=mki, _output_factory=mko, pinned_input="Jabra")
    await r.attach(devs)
    assert r.active_input.name == "Jabra SPEAK 410 USB"
    await r.shutdown()


@pytest.mark.asyncio
async def test_router_falls_back_when_pinned_missing(fake_streams):
    ins, outs, mki, mko = fake_streams
    devs = DeviceList(inputs=[_dev(0, "USB PnP Sound Device", "input")], outputs=[])
    r = AudioRouter(_input_factory=mki, _output_factory=mko, pinned_input="Jabra")
    await r.attach(devs)
    assert r.active_input.name == "USB PnP Sound Device"
    assert r.last_fallback == "input pin 'Jabra' not present; auto-picked 'USB PnP Sound Device'"
    await r.shutdown()
