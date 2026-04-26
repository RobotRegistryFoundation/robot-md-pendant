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


@pytest.mark.asyncio
async def test_router_stops_stream_when_device_disappears(fake_streams):
    """When a previously-active device unplugs, the router stops the stream
    and clears active_input. Most common Task 6 hot-plug path."""
    ins, outs, mki, mko = fake_streams
    devs = DeviceList(inputs=[_dev(0, "USB Mic", "input")], outputs=[])
    r = AudioRouter(_input_factory=mki, _output_factory=mko)
    await r.attach(devs)
    assert r.active_input is not None
    await r.update(DeviceList(inputs=[], outputs=[]))
    assert r.active_input is None
    assert ins[0].stopped is True
    await r.shutdown()


@pytest.mark.asyncio
async def test_router_update_with_same_device_is_noop(fake_streams):
    """No new stream is created and the old one is not stopped if the
    resolved device hasn't changed."""
    ins, outs, mki, mko = fake_streams
    devs = DeviceList(inputs=[_dev(0, "USB Mic", "input")], outputs=[])
    r = AudioRouter(_input_factory=mki, _output_factory=mko)
    await r.attach(devs)
    n_streams_before = len(ins)
    await r.update(devs)  # same DeviceList
    assert len(ins) == n_streams_before
    assert ins[0].stopped is False
    await r.shutdown()


@pytest.mark.asyncio
async def test_router_read_raises_when_no_active_input(fake_streams):
    ins, outs, mki, mko = fake_streams
    r = AudioRouter(_input_factory=mki, _output_factory=mko)
    with pytest.raises(RuntimeError, match="no active input"):
        await r.read()
    await r.shutdown()


@pytest.mark.asyncio
async def test_router_write_drops_silently_when_no_active_output(fake_streams):
    ins, outs, mki, mko = fake_streams
    r = AudioRouter(_input_factory=mki, _output_factory=mko)
    # No attach → no output stream → write should NOT raise
    await r.write(b"\x10\x00" * 160)
    await r.shutdown()


def test_router_set_pin_rejects_unknown_kind():
    r = AudioRouter()
    with pytest.raises(ValueError, match="unknown kind"):
        r.set_pin("microphone", "Jabra")  # not "input" or "output"


@pytest.mark.asyncio
async def test_router_update_lock_serializes_concurrent_calls(fake_streams):
    """Two concurrent update() calls must not race — the lock serializes them
    so no stream is double-stopped or orphaned."""
    ins, outs, mki, mko = fake_streams
    devs1 = DeviceList(inputs=[_dev(0, "Mic A", "input")], outputs=[])
    devs2 = DeviceList(inputs=[_dev(1, "Mic B", "input")], outputs=[])
    r = AudioRouter(_input_factory=mki, _output_factory=mko)
    await r.attach(devs1)
    # Fire two updates concurrently
    await asyncio.gather(r.update(devs2), r.update(devs1))
    # Final state is whichever update went second; the other was serialized cleanly
    assert r.active_input is not None
    # No stream should be both started AND not stopped except the most recent
    final_index = r.active_input.index
    for s in ins[:-1]:  # all but the most recent
        assert s.stopped is True, f"stream {s.device_index} not stopped"
    assert ins[-1].started is True
    await r.shutdown()
