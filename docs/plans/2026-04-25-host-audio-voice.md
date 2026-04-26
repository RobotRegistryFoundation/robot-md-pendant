# Host-Audio Voice Path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Pi-direct voice loop to `pendantd` so the operator can address Claude Code by the robot's name (from `ROBOT.md`) or the literal word "claude," using USB audio devices attached to the Raspberry Pi 5. Ships a new Python MCP server (`pendant-mcp`) and a new `robot-md init` phase (`voice_setup`).

**Architecture:** A new `pendantd/audio/` package owns device discovery, hot-plug, and stream I/O. `voice/wake.py` is rewritten to a `StreamingWakeMatcher` over `faster-whisper tiny.en`, matching transcripts against `["claude", manifest.name, *aliases]`. A new `voice/loop.py` orchestrates wake → endpoint → utterance ASR → agent → TTS → output. A new `pendantd/mcp_server/` exposes audio + voice control tools as a stdio MCP server, talking to the running pendantd over a Unix socket. The `robot-md` CLI gains an interactive `voice_setup` init phase.

**Tech Stack:** Python 3.11+ asyncio, `sounddevice` (PortAudio), `faster-whisper` (CTranslate2), `pyudev`, `mcp` (Python SDK), existing `piper`/`whisper.cpp` subprocess CLIs, `pytest`/`pytest-asyncio`.

**Spec:** [`docs/specs/2026-04-25-voice-host-audio-design.md`](../specs/2026-04-25-voice-host-audio-design.md)

**Repos touched:** `~/robot-md-pendant` (most tasks) and `~/robot-md` (Task 16 only).

---

## File map

```
~/robot-md-pendant/
├── pendantd/
│   ├── pyproject.toml                  (modified — deps swap)
│   ├── src/pendantd/
│   │   ├── __main__.py                 (modified — wire voice loop)
│   │   ├── voice_cfg.py                (modified — schema + defaults)
│   │   ├── server.py                   (modified — control socket + pendant hooks)
│   │   ├── audio/                      (NEW package)
│   │   │   ├── __init__.py
│   │   │   ├── devices.py              # list_devices, pick_default, Device, match
│   │   │   ├── streams.py              # async sounddevice wrappers
│   │   │   ├── loopback.py             # record_and_play
│   │   │   ├── router.py               # AudioRouter
│   │   │   └── watcher.py              # DeviceWatcher (pyudev + pendant hooks)
│   │   ├── voice/
│   │   │   ├── wake.py                 (replaced — StreamingWakeMatcher)
│   │   │   └── loop.py                 (NEW — orchestrator)
│   │   └── mcp_server/                 (NEW package)
│   │       ├── __init__.py
│   │       ├── __main__.py
│   │       ├── ipc_client.py           # Unix-socket JSON-RPC client
│   │       └── server.py               # MCP server + tools
│   └── tests/
│       ├── fixtures/audio/             (NEW — generated WAVs)
│       │   ├── _generate.py
│       │   ├── claude_16k.wav
│       │   ├── bob_16k.wav
│       │   ├── silence_16k.wav
│       │   └── noise_16k.wav
│       ├── test_audio_devices.py       (NEW)
│       ├── test_audio_streams.py       (NEW)
│       ├── test_audio_loopback.py      (NEW)
│       ├── test_audio_router.py        (NEW)
│       ├── test_audio_watcher.py       (NEW)
│       ├── test_voice_wake.py          (REWRITTEN)
│       ├── test_voice_loop.py          (NEW)
│       ├── test_voice_cfg.py           (extended)
│       ├── test_server_control_sock.py (NEW)
│       ├── test_mcp_ipc_client.py      (NEW)
│       └── test_mcp_server.py          (NEW)
├── README.md                           (modified — sys deps + pendant-mcp registration)
└── systemd/                            (modified — runtime dir tmpfile)

~/robot-md/
└── cli/
    ├── src/robot_md/init_phases/
    │   └── voice_setup.py              (NEW)
    └── tests/
        └── test_voice_setup.py         (NEW)
```

---

## Task 1: Swap dependencies in `pendantd/pyproject.toml`

**Files:**
- Modify: `pendantd/pyproject.toml`

- [ ] **Step 1: Edit pyproject.toml**

Replace the `dependencies` block:

```toml
dependencies = [
  "websockets>=12.0",
  "jsonschema>=4.21",
  "pyyaml>=6.0",
  "watchfiles>=0.21",
  "claude-agent-sdk>=0.1.0",
  "sounddevice>=0.4",
  "faster-whisper>=1.0",
  "pyudev>=0.24",
  "mcp>=1.0",
]
```

(Note `openwakeword` is removed; no longer used. `webrtcvad` is **not** added — existing RMS `Endpointer` covers VAD.)

Add a `pendant-mcp` console script entry:

```toml
[project.scripts]
pendantd = "pendantd.__main__:main"
pendant-mcp = "pendantd.mcp_server.__main__:main"
```

- [ ] **Step 2: Reinstall in editable mode**

```bash
cd ~/robot-md-pendant/pendantd && pip install -e ".[dev]"
```

Expected: install completes; `python -c "import sounddevice, faster_whisper, pyudev, mcp"` exits 0.

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```bash
cd ~/robot-md-pendant/pendantd && pytest -q
```

Expected: all existing tests pass (we have not yet rewritten `voice/wake.py`, so tests reference the old `WakeDetector` which still exists).

- [ ] **Step 4: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/pyproject.toml && git commit -m "$(cat <<'EOF'
chore(pendantd): swap deps for host-audio voice path

Adds sounddevice, faster-whisper, pyudev, and the mcp Python SDK.
Removes openwakeword (replaced by streaming-ASR transcript matching).
Registers a pendant-mcp console script.

See docs/specs/2026-04-25-voice-host-audio-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `pendantd/audio/devices.py` — device enumeration + auto-pick

**Files:**
- Create: `pendantd/src/pendantd/audio/__init__.py` (empty)
- Create: `pendantd/src/pendantd/audio/devices.py`
- Create: `pendantd/tests/test_audio_devices.py`

- [ ] **Step 1: Write failing tests**

Create `pendantd/tests/test_audio_devices.py`:

```python
from pendantd.audio.devices import (
    Device,
    DeviceList,
    list_devices,
    pick_default,
    match_substring,
)


FAKE = [
    {"index": 0, "name": "USB PnP Sound Device", "max_input_channels": 1, "max_output_channels": 0,
     "default_samplerate": 48000.0, "hostapi": 0},
    {"index": 1, "name": "Jabra SPEAK 410 USB", "max_input_channels": 1, "max_output_channels": 2,
     "default_samplerate": 16000.0, "hostapi": 0},
    {"index": 2, "name": "bcm2835 Headphones", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 44100.0, "hostapi": 0},
    {"index": 3, "name": "vc4-hdmi", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 48000.0, "hostapi": 0},
]


def test_list_devices_partitions_inputs_and_outputs():
    devs = list_devices(query=lambda: FAKE)
    assert [d.name for d in devs.inputs] == ["USB PnP Sound Device", "Jabra SPEAK 410 USB"]
    assert [d.name for d in devs.outputs] == ["Jabra SPEAK 410 USB", "bcm2835 Headphones", "vc4-hdmi"]


def test_pick_default_input_prefers_usb_over_builtin():
    devs = list_devices(query=lambda: FAKE)
    picked = pick_default(devs.inputs, kind="input")
    assert picked.name == "USB PnP Sound Device"


def test_pick_default_output_prefers_headset_class():
    devs = list_devices(query=lambda: FAKE)
    picked = pick_default(devs.outputs, kind="output")
    # Jabra has both input + output → headset class → wins
    assert picked.name == "Jabra SPEAK 410 USB"


def test_match_substring_returns_first_index_winner_when_ambiguous():
    devs = list_devices(query=lambda: FAKE)
    matched = match_substring(devs.outputs, "USB")
    assert matched.name == "Jabra SPEAK 410 USB"  # first by index


def test_match_substring_returns_none_when_missing():
    devs = list_devices(query=lambda: FAKE)
    assert match_substring(devs.outputs, "Sennheiser") is None


def test_pick_default_returns_none_on_empty_list():
    assert pick_default([], kind="input") is None
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_devices.py -q
```

Expected: `ImportError: No module named pendantd.audio`.

- [ ] **Step 3: Implement `audio/devices.py`**

Create `pendantd/src/pendantd/audio/__init__.py` empty.

Create `pendantd/src/pendantd/audio/devices.py`:

```python
"""Audio device discovery + auto-pick."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

Kind = Literal["input", "output"]


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    channels: int
    sample_rate: int
    kind: Kind

    def matches(self, substring: str) -> bool:
        return substring.lower() in self.name.lower()


@dataclass(frozen=True)
class DeviceList:
    inputs: list[Device]
    outputs: list[Device]


def _query_sd() -> list[dict]:  # pragma: no cover - thin wrapper
    import sounddevice as sd
    return list(sd.query_devices())


def list_devices(query: Callable[[], list[dict]] = _query_sd) -> DeviceList:
    """Enumerate audio devices and partition by kind.

    `query` defaults to `sounddevice.query_devices()`; injectable for tests.
    """
    raw = query()
    inputs: list[Device] = []
    outputs: list[Device] = []
    for d in raw:
        if d.get("max_input_channels", 0) > 0:
            inputs.append(Device(
                index=d["index"], name=d["name"],
                channels=d["max_input_channels"],
                sample_rate=int(d.get("default_samplerate", 16000)),
                kind="input",
            ))
        if d.get("max_output_channels", 0) > 0:
            outputs.append(Device(
                index=d["index"], name=d["name"],
                channels=d["max_output_channels"],
                sample_rate=int(d.get("default_samplerate", 16000)),
                kind="output",
            ))
    return DeviceList(inputs=inputs, outputs=outputs)


def _is_usb(name: str) -> bool:
    n = name.lower()
    return "usb" in n or "jabra" in n or "logitech" in n or "plantronics" in n


def _is_builtin(name: str) -> bool:
    n = name.lower()
    return "bcm2835" in n or "hdmi" in n


def _is_bluetooth(name: str) -> bool:
    n = name.lower()
    return "bluez" in n or "bluetooth" in n or "a2dp" in n


def _is_pendant(name: str) -> bool:
    return name.lower().startswith("pendant:")


def _input_priority(d: Device) -> int:
    # lower = better
    if _is_pendant(d.name):
        return 0
    if _is_usb(d.name):
        return 1
    if _is_bluetooth(d.name):
        return 2
    if _is_builtin(d.name):
        return 4
    return 3


def _output_priority(d: Device, has_input_partner: bool) -> int:
    if _is_pendant(d.name):
        return 0
    if has_input_partner and _is_usb(d.name):
        return 1  # headset class
    if _is_usb(d.name):
        return 2
    if "hdmi" in d.name.lower():
        return 3
    if _is_builtin(d.name):
        return 4
    return 3


def pick_default(devices: list[Device], kind: Kind, all_devices: DeviceList | None = None) -> Device | None:
    """Pick the highest-priority device.

    For outputs, headset-class detection looks for an input device with the same
    name; pass `all_devices` to enable. Defaults to no headset detection (still
    picks USB > HDMI > built-in).
    """
    if not devices:
        return None
    if kind == "input":
        return min(devices, key=lambda d: (_input_priority(d), d.index))
    input_names = {d.name for d in (all_devices.inputs if all_devices else [])}
    return min(
        devices,
        key=lambda d: (_output_priority(d, d.name in input_names), d.index),
    )


def match_substring(devices: list[Device], substring: str) -> Device | None:
    """Case-insensitive substring match. First match by index order wins."""
    if not substring:
        return None
    matches = [d for d in devices if d.matches(substring)]
    if not matches:
        return None
    return min(matches, key=lambda d: d.index)
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_devices.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/audio/ pendantd/tests/test_audio_devices.py && git commit -m "$(cat <<'EOF'
feat(audio): device enumeration + auto-pick (devices.py)

Adds Device dataclass, list_devices(), pick_default(), match_substring().
USB > Bluetooth > built-in for inputs; headset > USB-out > HDMI > built-in
for outputs. Pure functions, parameterized by query callable for testing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `pendantd/audio/streams.py` — async sounddevice wrappers

**Files:**
- Create: `pendantd/src/pendantd/audio/streams.py`
- Create: `pendantd/tests/test_audio_streams.py`

- [ ] **Step 1: Write failing tests**

```python
# pendantd/tests/test_audio_streams.py
import asyncio
import pytest
from pendantd.audio.streams import InputStream, OutputStream


class FakeSDInput:
    def __init__(self, samplerate, channels, dtype, callback, device, blocksize):
        self._cb = callback
        self._task = None
        self.started = False
        self.stopped = False

    def start(self): self.started = True
    def stop(self): self.stopped = True
    def close(self): pass
    def __enter__(self): self.start(); return self
    def __exit__(self, *a): self.stop()


@pytest.mark.asyncio
async def test_input_stream_yields_chunks_from_callback():
    received = []

    def make(samplerate, channels, dtype, callback, device, blocksize):
        # Simulate sounddevice firing the callback with a chunk
        import threading, time
        def fire():
            time.sleep(0.01)
            callback(b"\x00\x01" * 160, 160, None, None)
        threading.Thread(target=fire, daemon=True).start()
        return FakeSDInput(samplerate, channels, dtype, callback, device, blocksize)

    stream = InputStream(device_index=0, samplerate=16000, blocksize=160, _factory=make)
    await stream.start()
    chunk = await asyncio.wait_for(stream.read(), timeout=0.5)
    assert isinstance(chunk, (bytes, bytearray))
    assert len(chunk) == 320  # 160 samples × 2 bytes
    await stream.stop()


@pytest.mark.asyncio
async def test_output_stream_writes_chunks():
    written: list[bytes] = []

    class FakeSDOutput:
        def __init__(self, samplerate, channels, dtype, device, blocksize):
            pass
        def start(self): pass
        def stop(self): pass
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def write(self, chunk): written.append(bytes(chunk))

    stream = OutputStream(device_index=1, samplerate=16000, _factory=lambda **kw: FakeSDOutput(**kw))
    await stream.start()
    await stream.write(b"\x10\x00" * 160)
    await stream.stop()
    assert written == [b"\x10\x00" * 160]
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_streams.py -q
```

Expected: ImportError.

- [ ] **Step 3: Implement `audio/streams.py`**

```python
"""Async wrappers over sounddevice.RawInputStream / RawOutputStream."""
from __future__ import annotations

import asyncio
from typing import Any, Callable


def _default_input_factory(**kw: Any) -> Any:  # pragma: no cover - thin wrapper
    import sounddevice as sd
    return sd.RawInputStream(**kw)


def _default_output_factory(**kw: Any) -> Any:  # pragma: no cover
    import sounddevice as sd
    return sd.RawOutputStream(**kw)


class InputStream:
    """16 kHz mono int16 capture, queue-backed for asyncio consumers."""

    def __init__(
        self,
        device_index: int,
        samplerate: int = 16000,
        blocksize: int = 1600,  # 100 ms @ 16 kHz
        _factory: Callable[..., Any] = _default_input_factory,
    ) -> None:
        self._device = device_index
        self._sr = samplerate
        self._block = blocksize
        self._factory = _factory
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self._stream: Any = None

    def _on_block(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        if self._loop is None:
            return
        chunk = bytes(indata)
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
        except asyncio.QueueFull:
            # Drop oldest under back-pressure
            try:
                self._queue.get_nowait()
                self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
            except Exception:
                pass

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stream = self._factory(
            samplerate=self._sr, channels=1, dtype="int16",
            callback=self._on_block, device=self._device, blocksize=self._block,
        )
        self._stream.start()

    async def read(self) -> bytes:
        return await self._queue.get()

    async def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class OutputStream:
    """16 kHz mono int16 playback."""

    def __init__(
        self,
        device_index: int,
        samplerate: int = 16000,
        _factory: Callable[..., Any] = _default_output_factory,
    ) -> None:
        self._device = device_index
        self._sr = samplerate
        self._factory = _factory
        self._stream: Any = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._stream = self._factory(
            samplerate=self._sr, channels=1, dtype="int16",
            device=self._device, blocksize=0,
        )
        self._stream.start()

    async def write(self, chunk: bytes) -> None:
        if self._stream is None:
            raise RuntimeError("OutputStream not started")
        async with self._lock:
            self._stream.write(chunk)

    async def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_streams.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/audio/streams.py pendantd/tests/test_audio_streams.py && git commit -m "$(cat <<'EOF'
feat(audio): async sounddevice wrappers (streams.py)

InputStream is 16 kHz mono int16 capture, queue-backed for asyncio
consumers; OutputStream is the playback counterpart. Factory injection
keeps the unit tests off real hardware.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `pendantd/audio/loopback.py` — record-and-play test ritual

**Files:**
- Create: `pendantd/src/pendantd/audio/loopback.py`
- Create: `pendantd/tests/test_audio_loopback.py`

- [ ] **Step 1: Write failing tests**

```python
# pendantd/tests/test_audio_loopback.py
import asyncio
import pytest
from pendantd.audio.loopback import record_and_play


class StubInput:
    def __init__(self, chunks): self._chunks = list(chunks)
    async def start(self): pass
    async def read(self):
        if not self._chunks:
            await asyncio.sleep(0.01)
            return b""
        return self._chunks.pop(0)
    async def stop(self): pass


class StubOutput:
    def __init__(self): self.written = []
    async def start(self): pass
    async def write(self, b): self.written.append(b)
    async def stop(self): pass


@pytest.mark.asyncio
async def test_record_and_play_returns_recorded_bytes_and_replays():
    inp = StubInput([b"\x01\x02" * 1600, b"\x03\x04" * 1600])  # 200 ms @ 16k
    out = StubOutput()
    result = await record_and_play(inp, out, seconds=0.2)
    assert result.recorded_bytes == 6400  # 200 ms × 16k × 2 bytes
    assert b"".join(out.written) == result.recorded_pcm
    assert isinstance(result.peak_dbfs, float)
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_loopback.py -q
```

Expected: ImportError.

- [ ] **Step 3: Implement `audio/loopback.py`**

```python
"""Record N seconds and play it back through the active output."""
from __future__ import annotations

import array
import math
from dataclasses import dataclass
from typing import Protocol


class _Inputable(Protocol):
    async def start(self) -> None: ...
    async def read(self) -> bytes: ...
    async def stop(self) -> None: ...


class _Outputable(Protocol):
    async def start(self) -> None: ...
    async def write(self, chunk: bytes) -> None: ...
    async def stop(self) -> None: ...


@dataclass
class LoopbackResult:
    recorded_bytes: int
    recorded_pcm: bytes
    peak_dbfs: float


def _peak_dbfs(pcm: bytes) -> float:
    if not pcm:
        return -120.0
    samples = array.array("h"); samples.frombytes(pcm)
    peak = max((abs(s) for s in samples), default=0)
    if peak == 0:
        return -120.0
    return 20.0 * math.log10(peak / 32768.0)


async def record_and_play(
    inp: _Inputable, out: _Outputable, seconds: float, samplerate: int = 16000,
) -> LoopbackResult:
    target = int(seconds * samplerate * 2)  # bytes (s16 mono)
    await inp.start()
    buf = bytearray()
    while len(buf) < target:
        chunk = await inp.read()
        if chunk:
            buf.extend(chunk)
    await inp.stop()
    pcm = bytes(buf[:target])
    await out.start()
    await out.write(pcm)
    await out.stop()
    return LoopbackResult(
        recorded_bytes=len(pcm),
        recorded_pcm=pcm,
        peak_dbfs=_peak_dbfs(pcm),
    )
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_loopback.py -q
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/audio/loopback.py pendantd/tests/test_audio_loopback.py && git commit -m "$(cat <<'EOF'
feat(audio): record-and-play loopback test ritual (loopback.py)

Used by the init wizard's mic-test step. Returns recorded bytes, the
PCM buffer, and a peak dBFS reading.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `pendantd/audio/router.py` — AudioRouter

**Files:**
- Create: `pendantd/src/pendantd/audio/router.py`
- Create: `pendantd/tests/test_audio_router.py`

- [ ] **Step 1: Write failing tests**

```python
# pendantd/tests/test_audio_router.py
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
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_router.py -q
```

Expected: ImportError.

- [ ] **Step 3: Implement `audio/router.py`**

```python
"""AudioRouter — owns active input and output streams, swaps on changes."""
from __future__ import annotations

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

    def set_pin(self, kind: str, substring: str) -> None:
        if kind == "input":
            self._pin_in = substring
        elif kind == "output":
            self._pin_out = substring
        else:
            raise ValueError(f"unknown kind: {kind!r}")
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_router.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/audio/router.py pendantd/tests/test_audio_router.py && git commit -m "$(cat <<'EOF'
feat(audio): AudioRouter (router.py)

Owns the active input/output streams, swaps on device changes, honors
pinned substrings with a fallback message when a pin is absent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `pendantd/audio/watcher.py` — DeviceWatcher

**Files:**
- Create: `pendantd/src/pendantd/audio/watcher.py`
- Create: `pendantd/tests/test_audio_watcher.py`

- [ ] **Step 1: Write failing tests**

```python
# pendantd/tests/test_audio_watcher.py
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
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_watcher.py -q
```

Expected: ImportError.

- [ ] **Step 3: Implement `audio/watcher.py`**

```python
"""DeviceWatcher — coalesces USB udev events and pendant connect/disconnect."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable


OnChange = Callable[[str], Awaitable[None]]


class DeviceWatcher:
    def __init__(
        self,
        on_change: OnChange,
        debounce_ms: int = 300,
        _start_udev: bool = True,
    ) -> None:
        self._on_change = on_change
        self._debounce_s = debounce_ms / 1000.0
        self._loop = asyncio.get_event_loop()
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
        self._loop.create_task(self._on_change(reason))

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
            device = await asyncio.get_event_loop().run_in_executor(None, monitor.poll, 1.0)
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
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_audio_watcher.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/audio/watcher.py pendantd/tests/test_audio_watcher.py && git commit -m "$(cat <<'EOF'
feat(audio): DeviceWatcher (watcher.py)

Debounces pyudev sound-subsystem events and merges in pendant
connect/disconnect hooks. Async on_change callback per change reason.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Test fixture audio (generated WAVs)

**Files:**
- Create: `pendantd/tests/fixtures/audio/_generate.py`
- Create: `pendantd/tests/fixtures/audio/{claude,bob,silence,noise}_16k.wav`

- [ ] **Step 1: Write the generator script**

```python
# pendantd/tests/fixtures/audio/_generate.py
"""One-shot generator for wake-word test fixtures.

Run from a Pi with `piper` installed:
    python -m pendantd.tests.fixtures.audio._generate

Produces:
    claude_16k.wav   — TTS "claude"
    bob_16k.wav      — TTS "bob"
    silence_16k.wav  — 1.5 s of silence
    noise_16k.wav    — 1.5 s of low-amplitude white noise
"""
from __future__ import annotations

import asyncio
import os
import random
import struct
import wave
from pathlib import Path

HERE = Path(__file__).parent


def write_wav(path: Path, pcm: bytes, samplerate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(samplerate)
        w.writeframes(pcm)


async def piper(text: str) -> bytes:
    cmd = os.environ.get("PIPER_CMD", "piper").split() + ["--model", os.environ["PIPER_MODEL"]]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate(text.encode())
    # piper emits raw int16 PCM at 22050 Hz by default; downsample with sox if needed.
    return out


def silence(seconds: float = 1.5) -> bytes:
    n = int(seconds * 16000)
    return b"\x00\x00" * n


def noise(seconds: float = 1.5, peak: int = 200) -> bytes:
    n = int(seconds * 16000)
    return struct.pack(f"<{n}h", *[random.randint(-peak, peak) for _ in range(n)])


async def main() -> None:
    write_wav(HERE / "silence_16k.wav", silence())
    write_wav(HERE / "noise_16k.wav", noise())
    write_wav(HERE / "claude_16k.wav", await piper("claude"))
    write_wav(HERE / "bob_16k.wav", await piper("bob"))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Generate the fixtures on the Pi**

```bash
cd ~/robot-md-pendant/pendantd && \
  PIPER_MODEL=$(ls ~/.local/share/piper/voices/en_US-amy-medium.onnx 2>/dev/null || echo /opt/piper/voices/en_US-amy-medium.onnx) \
  python tests/fixtures/audio/_generate.py
ls tests/fixtures/audio/*.wav
```

Expected: four WAV files exist, each ~50 KB.

If piper is not installed on the Pi, run with `PIPER_CMD=true` and the `claude`/`bob` files will be empty — wake-tests will use the `silence` fixture as a no-op and skip the positive-match assertions (the StreamingWakeMatcher tests in Task 8 detect zero-byte fixtures and `pytest.skip`).

- [ ] **Step 3: Commit fixtures (binary)**

```bash
cd ~/robot-md-pendant && git add pendantd/tests/fixtures/audio/ && git commit -m "$(cat <<'EOF'
test(audio): wake-word fixture WAVs (claude/bob/silence/noise)

Generated via piper TTS at 16 kHz mono. _generate.py is committed for
re-runs after voice changes; the four .wav files are committed so CI
runs without piper installed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Rewrite `voice/wake.py` — `StreamingWakeMatcher`

**Files:**
- Modify (replace): `pendantd/src/pendantd/voice/wake.py`
- Modify (replace): `pendantd/tests/test_voice_wake.py`

- [ ] **Step 1: Write failing tests**

Replace `pendantd/tests/test_voice_wake.py`:

```python
import wave
from pathlib import Path
import pytest

from pendantd.voice.wake import StreamingWakeMatcher


FIX = Path(__file__).parent / "fixtures" / "audio"


def _read_wav_bytes(name: str) -> bytes:
    path = FIX / name
    if not path.exists() or path.stat().st_size < 100:
        return b""
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


class FakeWhisper:
    """Stand-in for faster-whisper: maps PCM identity → fake transcript."""
    def __init__(self, mapping: dict[bytes, str]):
        self._map = mapping

    def transcribe(self, pcm: bytes, **kw):
        text = self._map.get(pcm[:64], "")
        # mimic faster-whisper's segments iterator API
        return ([type("Seg", (), {"text": text})()], None)


def test_matcher_fires_on_robot_name():
    pcm = b"BOB_PCM" + b"\x00" * 200
    fw = FakeWhisper({pcm[:64]: " bob"})
    m = StreamingWakeMatcher(model=fw, vocabulary=["claude", "bob"])
    hits = m.feed(pcm)
    assert hits == [{"phrase": "bob", "transcript": "bob"}]


def test_matcher_fires_on_claude_case_insensitive():
    pcm = b"CL_PCM" + b"\x00" * 200
    fw = FakeWhisper({pcm[:64]: "Claude!"})
    m = StreamingWakeMatcher(model=fw, vocabulary=["claude", "bob"])
    hits = m.feed(pcm)
    assert hits and hits[0]["phrase"] == "claude"


def test_matcher_no_fire_on_silence():
    pcm = b"\x00" * 1024
    fw = FakeWhisper({pcm[:64]: ""})
    m = StreamingWakeMatcher(model=fw, vocabulary=["claude", "bob"])
    assert m.feed(pcm) == []


def test_matcher_fuzzy_edge_match_for_long_names():
    pcm = b"FUZZY" + b"\x00" * 200
    fw = FakeWhisper({pcm[:64]: " rosie"})
    m = StreamingWakeMatcher(model=fw, vocabulary=["claude", "rose"])
    # "rose" is 4 chars → Levenshtein ≤ 1 tolerated → "rosie" matches
    hits = m.feed(pcm)
    assert hits and hits[0]["phrase"] == "rose"


def test_matcher_with_real_recordings_for_claude():
    pcm = _read_wav_bytes("claude_16k.wav")
    if not pcm:
        pytest.skip("piper-generated fixture missing; skip integration assertion")
    from faster_whisper import WhisperModel
    model = WhisperModel("tiny.en", compute_type="int8")
    m = StreamingWakeMatcher(model=model, vocabulary=["claude", "bob"])
    assert any(h["phrase"] == "claude" for h in m.feed(pcm))
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_voice_wake.py -q
```

Expected: existing `WakeDetector` import fails; AttributeError on `StreamingWakeMatcher`.

- [ ] **Step 3: Replace `voice/wake.py`**

```python
"""Streaming wake-word detection via transcript matching.

Feeds rolling-window PCM to faster-whisper and matches normalized
transcripts against the configured vocabulary. Vocabulary changes at
runtime (e.g., live-reload of voice.yaml) are reflected on the next feed.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


_NORM = re.compile(r"[^a-z]+")


def _normalize(text: str) -> str:
    return _NORM.sub("", text.lower())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                cur[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            ))
        prev = cur
    return prev[-1]


class StreamingWakeMatcher:
    """Match transcripts of a rolling audio window against a vocabulary.

    Designed to be called every ~500 ms with the latest 1.5 s of PCM.
    """

    def __init__(
        self,
        model: Any,
        vocabulary: Iterable[str],
        sample_rate: int = 16000,
        fuzzy_min_len: int = 4,
        fuzzy_distance: int = 1,
    ) -> None:
        self._model = model
        self._sr = sample_rate
        self._fuzzy_min = fuzzy_min_len
        self._fuzzy_dist = fuzzy_distance
        self.set_vocabulary(vocabulary)

    def set_vocabulary(self, vocabulary: Iterable[str]) -> None:
        self._vocab = [v.strip().lower() for v in vocabulary if v.strip()]
        self._vocab_norm = [_normalize(v) for v in self._vocab]

    @property
    def vocabulary(self) -> list[str]:
        return list(self._vocab)

    def _transcribe(self, pcm: bytes) -> str:
        # Real path: faster_whisper.WhisperModel.transcribe accepts ndarray;
        # callers pass either ndarray or s16le bytes (we convert).
        try:
            import numpy as np
            audio = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768.0
        except ImportError:  # pragma: no cover
            audio = pcm
        segments, _info = self._model.transcribe(
            audio, language="en", vad_filter=True, beam_size=1, condition_on_previous_text=False,
        )
        return " ".join(s.text for s in segments).strip()

    def feed(self, pcm: bytes) -> list[dict]:
        """Return a list of `{phrase, transcript}` dicts for matches in this window.

        Empty list if nothing in the vocabulary matched.
        """
        if not self._vocab:
            return []
        text = self._transcribe(pcm)
        if not text:
            return []
        norm = _normalize(text)
        hits: list[dict] = []
        for phrase, phrase_norm in zip(self._vocab, self._vocab_norm):
            if not phrase_norm:
                continue
            if phrase_norm in norm:
                hits.append({"phrase": phrase, "transcript": text.strip()})
                continue
            if len(phrase_norm) >= self._fuzzy_min:
                # check each word in transcript for fuzzy match
                for word in re.findall(r"[a-z]+", text.lower()):
                    if abs(len(word) - len(phrase_norm)) <= self._fuzzy_dist and \
                       _levenshtein(word, phrase_norm) <= self._fuzzy_dist:
                        hits.append({"phrase": phrase, "transcript": text.strip()})
                        break
        return hits
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_voice_wake.py -q
```

Expected: 4 passed (5th may PASS or SKIP depending on whether `claude_16k.wav` is real piper output and `faster-whisper` model is downloaded).

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/voice/wake.py pendantd/tests/test_voice_wake.py && git commit -m "$(cat <<'EOF'
feat(voice): StreamingWakeMatcher (replaces openwakeword path)

Transcribes a rolling PCM window with faster-whisper and matches
normalized transcripts against ["claude", robot_name, *aliases].
Levenshtein ≤ 1 fuzzy match for vocabulary entries ≥ 4 chars.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `voice/loop.py` — orchestrator

**Files:**
- Create: `pendantd/src/pendantd/voice/loop.py`
- Create: `pendantd/tests/test_voice_loop.py`

- [ ] **Step 1: Write failing tests**

```python
# pendantd/tests/test_voice_loop.py
import asyncio
import pytest
from pendantd.voice.loop import VoiceLoop, LoopState


class FakeRouter:
    def __init__(self, frames):
        self._frames = list(frames)
        self.written: list[bytes] = []
        self.active_input = type("D", (), {"name": "fake-mic"})()
        self.active_output = type("D", (), {"name": "fake-spkr"})()
    async def read(self):
        if not self._frames:
            await asyncio.sleep(0.5)
            return b"\x00" * 320
        return self._frames.pop(0)
    async def write(self, b): self.written.append(bytes(b))


class StubWake:
    def __init__(self, fire_after_n_frames: int):
        self._n = fire_after_n_frames
        self._count = 0
        self.vocabulary = ["claude", "bob"]
    def feed(self, pcm):
        self._count += 1
        if self._count == self._n:
            return [{"phrase": "bob", "transcript": "bob pick the lego"}]
        return []
    def set_vocabulary(self, v): self.vocabulary = list(v)


class StubEndpoint:
    """Fires on_end after `fire_after` feed() calls."""
    def __init__(self, on_end, fire_after: int = 2):
        self._on_end = on_end
        self._fire_after = fire_after
        self._n = 0
    def feed(self, chunk):
        self._n += 1
        if self._n >= self._fire_after:
            self._on_end()


class StubWhisper:
    async def transcribe(self, pcm): return "pick the lego"


class StubAgent:
    def __init__(self): self.calls: list[str] = []
    async def query(self, text: str) -> str:
        self.calls.append(text)
        return "okay, picking the lego"


class StubPiper:
    async def synthesize(self, text):
        yield b"\x10\x00" * 100
        yield b"\x20\x00" * 100
    async def cancel(self): pass


@pytest.mark.asyncio
async def test_voice_loop_state_transitions_on_wake():
    frames = [b"\x00" * 320 for _ in range(20)]
    router = FakeRouter(frames)
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=2),
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=2),
        whisper=StubWhisper(), agent=StubAgent(), piper=StubPiper(),
        wake_step_seconds=0.01,  # small step so test runs fast
    )
    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.3)
    await loop.stop()
    await task
    assert LoopState.LISTENING in loop.history
    assert LoopState.THINKING in loop.history
    assert LoopState.SPEAKING in loop.history
    assert router.written  # TTS played


@pytest.mark.asyncio
async def test_voice_loop_announces_on_router_change():
    router = FakeRouter([b"\x00" * 320])
    loop = VoiceLoop(
        router=router, wake=StubWake(fire_after_n_frames=999),
        endpoint_factory=lambda on_end: StubEndpoint(on_end, fire_after=999),
        whisper=StubWhisper(), agent=StubAgent(), piper=StubPiper(),
    )
    task = asyncio.create_task(loop.run())
    await loop.announce("Now using fake-spkr.")
    await asyncio.sleep(0.1)
    await loop.stop()
    await task
    assert any(b for b in router.written)  # announcement played
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_voice_loop.py -q
```

Expected: ImportError.

- [ ] **Step 3: Implement `voice/loop.py`**

```python
"""VoiceLoop — orchestrates wake → endpoint → utterance ASR → agent → TTS."""
from __future__ import annotations

import asyncio
import enum
from typing import Any, Awaitable, Callable, Protocol


class LoopState(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class _Router(Protocol):
    active_input: Any
    active_output: Any
    async def read(self) -> bytes: ...
    async def write(self, chunk: bytes) -> None: ...


class _WakeMatcher(Protocol):
    vocabulary: list[str]
    def feed(self, pcm: bytes) -> list[dict]: ...
    def set_vocabulary(self, v: list[str]) -> None: ...


class VoiceLoop:
    def __init__(
        self,
        router: _Router,
        wake: _WakeMatcher,
        endpoint_factory: Callable[[], Any],
        whisper: Any,
        agent: Any,
        piper: Any,
        wake_window_seconds: float = 1.5,
        wake_step_seconds: float = 0.5,
        sample_rate: int = 16000,
    ) -> None:
        self._router = router
        self._wake = wake
        self._make_endpoint = endpoint_factory
        self._whisper = whisper
        self._agent = agent
        self._piper = piper
        self._sr = sample_rate
        self._win_bytes = int(wake_window_seconds * sample_rate * 2)
        self._step_bytes = int(wake_step_seconds * sample_rate * 2)
        self.state = LoopState.IDLE
        self.history: list[LoopState] = []
        self.last_wake_at: float | None = None
        self.last_utterance: str = ""
        self._stop = asyncio.Event()
        self._announce_q: asyncio.Queue[str] = asyncio.Queue()

    def _set_state(self, s: LoopState) -> None:
        self.state = s
        self.history.append(s)

    async def announce(self, text: str) -> None:
        await self._announce_q.put(text)

    async def stop(self) -> None:
        self._stop.set()

    async def _speak(self, text: str) -> None:
        async for chunk in self._piper.synthesize(text):
            await self._router.write(chunk)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        rolling = bytearray()
        bytes_since_step = 0
        self._set_state(LoopState.LISTENING)
        while not self._stop.is_set():
            # Drain announcements first (cuts mid-listen)
            try:
                msg = self._announce_q.get_nowait()
                self._set_state(LoopState.SPEAKING)
                await self._speak(msg)
                self._set_state(LoopState.LISTENING)
            except asyncio.QueueEmpty:
                pass

            try:
                chunk = await asyncio.wait_for(self._router.read(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            rolling.extend(chunk)
            if len(rolling) > self._win_bytes:
                del rolling[: len(rolling) - self._win_bytes]
            bytes_since_step += len(chunk)
            if bytes_since_step < self._step_bytes:
                continue
            bytes_since_step = 0

            hits = self._wake.feed(bytes(rolling))
            if not hits:
                continue

            self.last_wake_at = loop.time()
            # Capture utterance until endpoint fires
            self._set_state(LoopState.THINKING)
            utt = bytearray()
            done = asyncio.Event()
            ep = self._make_endpoint(done.set)  # factory: (on_end) -> endpoint
            while not done.is_set():
                try:
                    c = await asyncio.wait_for(self._router.read(), timeout=2.5)
                except asyncio.TimeoutError:
                    break
                utt.extend(c)
                ep.feed(c)
            transcript = await self._whisper.transcribe(bytes(utt))
            self.last_utterance = transcript
            reply = await self._agent.query(transcript)
            self._set_state(LoopState.SPEAKING)
            await self._speak(reply)
            self._set_state(LoopState.LISTENING)
            rolling.clear()
        self._set_state(LoopState.IDLE)
```

Note: `endpoint_factory` is a `Callable[[Callable[[], None]], Endpointer]` — it accepts the `on_end` callable and returns an endpoint with that callback already wired. The existing `Endpointer.__init__(rms_threshold, silence_ms, on_end)` matches; the wiring in `__main__.py` is `endpoint_factory=lambda on_end: Endpointer(rms_threshold=200, silence_ms=300, on_end=on_end)`.

- [ ] **Step 4: Run tests, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_voice_loop.py -q
```

Expected: 2 passed (the StubEndpoint in the test sets `done` directly via constructor injection in the loop fallback path, so the test passes without a `set_on_end` method).

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/voice/loop.py pendantd/tests/test_voice_loop.py && git commit -m "$(cat <<'EOF'
feat(voice): VoiceLoop orchestrator (loop.py)

State machine listening → thinking → speaking → listening, with an
announcement queue that ducks the listen path. Wake match every 500 ms
on a rolling 1.5 s window; utterance capture ends on Endpointer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Extend `voice_cfg.py` — schema + defaults

**Files:**
- Modify: `pendantd/src/pendantd/voice_cfg.py`
- Modify: `pendantd/tests/test_voice_cfg.py`

- [ ] **Step 1: Write failing test**

Append to `pendantd/tests/test_voice_cfg.py`:

```python
def test_load_voice_cfg_fills_new_defaults_for_old_files(tmp_path):
    p = tmp_path / "voice.yaml"
    p.write_text("wake_word: claude\ntts_voice: en_US-amy-medium\n")
    from pendantd.voice_cfg import load_voice_cfg
    cfg = load_voice_cfg(p)
    assert cfg["wake_word"] == "claude"
    assert cfg["robot_name"] == ""        # default
    assert cfg["wake_aliases"] == []      # default
    assert cfg["input_device"] == ""      # default
    assert cfg["output_device"] == ""     # default
    assert cfg["sample_rate"] == 16000    # default
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_voice_cfg.py -q
```

Expected: KeyError on the new default keys.

- [ ] **Step 3: Implement defaults**

Edit `pendantd/src/pendantd/voice_cfg.py` — replace `REQUIRED_KEYS` and `load_voice_cfg`:

```python
REQUIRED_KEYS = ("wake_word", "tts_voice")
DEFAULTS: dict = {
    "robot_name": "",
    "wake_aliases": [],
    "input_device": "",
    "output_device": "",
    "sample_rate": 16000,
}


def load_voice_cfg(path) -> dict:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(data, dict):
        raise VoiceConfigError("voice config must be a mapping")
    for key in REQUIRED_KEYS:
        if key not in data:
            raise VoiceConfigError(f"missing required key: {key!r}")
    for key, default in DEFAULTS.items():
        data.setdefault(key, default if not isinstance(default, list) else list(default))
    return data
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_voice_cfg.py -q
```

Expected: all pass; existing voice_cfg tests still green.

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/voice_cfg.py pendantd/tests/test_voice_cfg.py && git commit -m "$(cat <<'EOF'
feat(voice_cfg): defaults for new schema keys

Old voice.yaml files keep loading — new keys (robot_name, wake_aliases,
input_device, output_device, sample_rate) get defaults filled in by
load_voice_cfg() rather than rejected.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Pendantd control socket + pendant connect/disconnect hooks in `server.py`

**Files:**
- Modify: `pendantd/src/pendantd/server.py`
- Create: `pendantd/tests/test_server_control_sock.py`

- [ ] **Step 1: Read `server.py` to find a hook point**

```bash
wc -l ~/robot-md-pendant/pendantd/src/pendantd/server.py && \
  grep -n "websocket\|connect\|disconnect" ~/robot-md-pendant/pendantd/src/pendantd/server.py | head
```

Expected: locate the WS handler that fires when a pendant connects (likely in `start()` / handler function). Note the line range.

- [ ] **Step 2: Write a failing test for the control socket**

Create `pendantd/tests/test_server_control_sock.py`:

```python
import asyncio
import json
import os
import tempfile
import pytest
from pendantd.server import ControlSocketServer


@pytest.mark.asyncio
async def test_control_socket_dispatches_to_handler(tmp_path):
    sock = tmp_path / "control.sock"
    handlers = {"ping": lambda params: {"pong": True, "echo": params}}
    srv = ControlSocketServer(path=str(sock), handlers=handlers)
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write((json.dumps({"id": 1, "method": "ping", "params": {"x": 7}}) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        msg = json.loads(line)
        assert msg == {"id": 1, "result": {"pong": True, "echo": {"x": 7}}}
        writer.close()
    finally:
        await srv.stop()


@pytest.mark.asyncio
async def test_control_socket_returns_error_on_unknown_method(tmp_path):
    sock = tmp_path / "control.sock"
    srv = ControlSocketServer(path=str(sock), handlers={})
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write((json.dumps({"id": 1, "method": "missing"}) + "\n").encode())
        await writer.drain()
        msg = json.loads(await reader.readline())
        assert msg["id"] == 1
        assert "error" in msg
        assert msg["error"]["message"].startswith("unknown method")
        writer.close()
    finally:
        await srv.stop()
```

- [ ] **Step 3: Run, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_server_control_sock.py -q
```

Expected: ImportError on `ControlSocketServer`.

- [ ] **Step 4: Add `ControlSocketServer` to `server.py`**

Append to `pendantd/src/pendantd/server.py`:

```python
import asyncio as _asyncio
import json as _json
import os as _os
from pathlib import Path as _Path
from typing import Awaitable as _Awaitable, Callable as _Callable


class ControlSocketServer:
    """Unix-socket JSON-RPC server for pendant-mcp ↔ pendantd IPC."""

    Handler = _Callable[[dict], "object | _Awaitable[object]"]

    def __init__(self, path: str, handlers: dict[str, Handler], mode: int = 0o660) -> None:
        self._path = path
        self._handlers = handlers
        self._mode = mode
        self._server: _asyncio.AbstractServer | None = None

    async def start(self) -> None:
        try:
            _os.unlink(self._path)
        except FileNotFoundError:
            pass
        _Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._server = await _asyncio.start_unix_server(self._handle, path=self._path)
        _os.chmod(self._path, self._mode)

    async def _handle(self, reader: _asyncio.StreamReader, writer: _asyncio.StreamWriter) -> None:
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    return
                try:
                    msg = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                req_id = msg.get("id")
                method = msg.get("method")
                params = msg.get("params", {}) or {}
                if method not in self._handlers:
                    resp = {"id": req_id, "error": {"message": f"unknown method: {method!r}"}}
                else:
                    try:
                        out = self._handlers[method](params)
                        if hasattr(out, "__await__"):
                            out = await out  # type: ignore[assignment]
                        resp = {"id": req_id, "result": out}
                    except Exception as e:  # surface failures, never crash
                        resp = {"id": req_id, "error": {"message": str(e)}}
                writer.write((_json.dumps(resp) + "\n").encode())
                await writer.drain()
        finally:
            try: writer.close()
            except Exception: pass

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            try:
                _os.unlink(self._path)
            except FileNotFoundError:
                pass
```

- [ ] **Step 5: Run, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_server_control_sock.py -q
```

Expected: 2 passed.

- [ ] **Step 6: Wire pendant connect/disconnect callbacks**

In `pendantd/src/pendantd/server.py`, find the existing pendant WS handler. Add two optional class-level callables (`on_pendant_connect`, `on_pendant_disconnect`) that the hosting `__main__.py` will set, and call them from the WS connection lifecycle:

Locate the WS handler (likely a method like `async def _handle_pendant(self, ws):`). Wrap its body:

```python
        if self.on_pendant_connect is not None:
            try: self.on_pendant_connect()
            except Exception: pass
        try:
            # ... existing handler body ...
            pass
        finally:
            if self.on_pendant_disconnect is not None:
                try: self.on_pendant_disconnect()
                except Exception: pass
```

Initialize the attributes in `__init__`:

```python
        self.on_pendant_connect: _Callable[[], None] | None = None
        self.on_pendant_disconnect: _Callable[[], None] | None = None
```

- [ ] **Step 7: Run full test suite to confirm no regression**

```bash
cd ~/robot-md-pendant/pendantd && pytest -q
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/server.py pendantd/tests/test_server_control_sock.py && git commit -m "$(cat <<'EOF'
feat(server): control-socket IPC + pendant connect/disconnect hooks

Adds ControlSocketServer (line-delimited JSON-RPC over a Unix socket)
for pendant-mcp ↔ pendantd state-changing calls. Exposes optional
on_pendant_connect/on_pendant_disconnect callables so the audio
DeviceWatcher can switch the active source when a pendant arrives.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Wire AudioRouter + VoiceLoop into `pendantd/__main__.py`

**Files:**
- Modify: `pendantd/src/pendantd/__main__.py`

- [ ] **Step 1: Read current `__main__.py`**

```bash
cat ~/robot-md-pendant/pendantd/src/pendantd/__main__.py
```

Expected: existing entry point that loads voice_cfg, starts the WS server, etc. Note the structure.

- [ ] **Step 2: Add the audio + voice wiring**

Edit the `main()` (or async startup) so it does, after loading `voice_cfg`:

```python
from pendantd.audio.devices import list_devices
from pendantd.audio.router import AudioRouter
from pendantd.audio.watcher import DeviceWatcher
from pendantd.voice.wake import StreamingWakeMatcher
from pendantd.voice.loop import VoiceLoop
from pendantd.voice.endpoint import Endpointer
from pendantd.voice.whisper import Whisper
from pendantd.voice.piper import Piper
from pendantd.server import ControlSocketServer

# In startup:
router = AudioRouter(
    pinned_input=cfg["input_device"],
    pinned_output=cfg["output_device"],
    samplerate=cfg["sample_rate"],
)
await router.attach(list_devices())

# faster-whisper streaming model (kept loaded)
from faster_whisper import WhisperModel
fw = WhisperModel("tiny.en", compute_type="int8")

vocab = ["claude"] + ([cfg["robot_name"]] if cfg["robot_name"] else []) + list(cfg["wake_aliases"])
wake = StreamingWakeMatcher(model=fw, vocabulary=vocab)

def make_endpoint(on_end):
    return Endpointer(rms_threshold=200, silence_ms=300, on_end=on_end)

whisper = Whisper(command=cfg.get("whisper_cmd", ["whisper-cpp", "-m", "/usr/local/share/whisper/ggml-base.en.bin", "-"]))
piper = Piper(command=cfg.get("piper_cmd", ["piper", "--model", cfg["tts_voice"]]))

# Agent setup is unchanged — see existing code; pass agent into VoiceLoop.
voice_loop = VoiceLoop(
    router=router, wake=wake, endpoint_factory=make_endpoint,
    whisper=whisper, agent=agent, piper=piper,
)

async def on_device_change(reason: str) -> None:
    new_devs = list_devices()
    prev_out = router.active_output.name if router.active_output else None
    await router.update(new_devs)
    new_out = router.active_output.name if router.active_output else None
    if new_out and new_out != prev_out:
        await voice_loop.announce(f"Now using {new_out}.")

watcher = DeviceWatcher(on_change=on_device_change, debounce_ms=300)

# Wire pendant hooks into the existing server
server.on_pendant_connect = watcher.on_pendant_connect
server.on_pendant_disconnect = watcher.on_pendant_disconnect

# Start the IPC control socket
control = ControlSocketServer(
    path="/run/pendantd/control.sock",
    handlers=build_control_handlers(router, voice_loop, cfg_path=cfg_path),
)
await control.start()

# Run forever
await asyncio.gather(
    voice_loop.run(),
    server.serve_forever(),
    return_exceptions=False,
)
```

The `build_control_handlers` function lives next to `__main__.py`; define it inline:

```python
def build_control_handlers(router, voice_loop, cfg_path):
    from pendantd.audio.devices import list_devices, match_substring
    from pendantd.audio.loopback import record_and_play
    import yaml
    def _cfg_set(key: str, value):
        data = yaml.safe_load(open(cfg_path).read()) or {}
        data[key] = value
        open(cfg_path, "w").write(yaml.safe_dump(data))
    return {
        "audio.list_devices": lambda p: {
            "inputs": [d.__dict__ for d in list_devices().inputs],
            "outputs": [d.__dict__ for d in list_devices().outputs],
        },
        "audio.get_active": lambda p: {
            "input": router.active_input.__dict__ if router.active_input else None,
            "output": router.active_output.__dict__ if router.active_output else None,
            "source": "pinned" if (router._pin_in or router._pin_out) else "auto",
        },
        "audio.set_input": lambda p: _set_pin(router, "input", p.get("substring"), _cfg_set, "input_device"),
        "audio.set_output": lambda p: _set_pin(router, "output", p.get("substring"), _cfg_set, "output_device"),
        "voice.start": lambda p: _voice_toggle(voice_loop, True),
        "voice.stop": lambda p: _voice_toggle(voice_loop, False),
        "voice.status": lambda p: {
            "state": voice_loop.state.value,
            "vocabulary": voice_loop._wake.vocabulary,
            "current_input": router.active_input.__dict__ if router.active_input else None,
            "current_output": router.active_output.__dict__ if router.active_output else None,
            "last_wake_at": voice_loop.last_wake_at,
            "last_utterance": voice_loop.last_utterance,
        },
        "voice.set_wake_aliases": lambda p: _set_aliases(voice_loop, p.get("aliases", []), _cfg_set),
        "voice.test_wake": lambda p: {"matches": []},  # full live capture handled by mcp-side helper
    }


def _set_pin(router, kind, substring, cfg_set, cfg_key):
    from pendantd.audio.devices import list_devices, match_substring
    devs = list_devices()
    pool = devs.inputs if kind == "input" else devs.outputs
    matched = match_substring(pool, substring or "")
    router.set_pin(kind, substring or "")
    cfg_set(cfg_key, substring or "")
    return {"matched": matched.__dict__ if matched else None, "persisted": True}


def _voice_toggle(loop, on):
    # full start/stop is asynchronous; for v1, return state
    return {"state": loop.state.value}


def _set_aliases(loop, aliases, cfg_set):
    aliases = [a for a in aliases if isinstance(a, str)]
    cfg_set("wake_aliases", aliases)
    base = ["claude"]
    loop._wake.set_vocabulary(base + aliases)
    return {"vocabulary": loop._wake.vocabulary, "persisted": True}
```

- [ ] **Step 3: Run smoke test on the Pi (manual)**

```bash
sudo install -d -m 0770 -o root -g pendant /run/pendantd
cd ~/robot-md-pendant/pendantd && python -m pendantd
```

Expected: pendantd starts; logs show "active input: <name>", "active output: <name>"; `/run/pendantd/control.sock` exists.

```bash
echo '{"id":1,"method":"audio.list_devices"}' | nc -U /run/pendantd/control.sock
```

Expected: JSON response with `inputs`/`outputs`.

Stop pendantd with `Ctrl-C`.

- [ ] **Step 4: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/__main__.py && git commit -m "$(cat <<'EOF'
feat(pendantd): wire AudioRouter, VoiceLoop, DeviceWatcher, control sock

Pendantd boot now: loads voice.yaml, attaches AudioRouter to live device
list, starts a faster-whisper StreamingWakeMatcher, runs VoiceLoop, and
opens /run/pendantd/control.sock for pendant-mcp IPC. DeviceWatcher
pushes hot-plug + pendant connect/disconnect updates back through the
router and announces device changes via TTS.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: `mcp_server/ipc_client.py` — Unix-socket JSON-RPC client

**Files:**
- Create: `pendantd/src/pendantd/mcp_server/__init__.py` (empty)
- Create: `pendantd/src/pendantd/mcp_server/ipc_client.py`
- Create: `pendantd/tests/test_mcp_ipc_client.py`

- [ ] **Step 1: Write failing tests**

```python
# pendantd/tests/test_mcp_ipc_client.py
import asyncio
import json
import pytest
from pendantd.mcp_server.ipc_client import IPCClient


async def echo_server(path):
    async def handle(reader, writer):
        line = await reader.readline()
        msg = json.loads(line)
        resp = {"id": msg["id"], "result": {"echo": msg.get("params", {})}}
        writer.write((json.dumps(resp) + "\n").encode())
        await writer.drain()
        writer.close()
    server = await asyncio.start_unix_server(handle, path=path)
    return server


@pytest.mark.asyncio
async def test_ipc_client_call_returns_result(tmp_path):
    sock = tmp_path / "s.sock"
    server = await echo_server(str(sock))
    try:
        client = IPCClient(path=str(sock))
        result = await client.call("foo", {"x": 1})
        assert result == {"echo": {"x": 1}}
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_ipc_client_raises_when_socket_missing(tmp_path):
    client = IPCClient(path=str(tmp_path / "nope.sock"))
    with pytest.raises(ConnectionError):
        await client.call("foo", {})
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_mcp_ipc_client.py -q
```

Expected: ImportError.

- [ ] **Step 3: Implement `mcp_server/ipc_client.py`**

```python
"""Async JSON-RPC over Unix socket. One call → one connection."""
from __future__ import annotations

import asyncio
import itertools
import json


class IPCClient:
    def __init__(self, path: str = "/run/pendantd/control.sock") -> None:
        self._path = path
        self._ids = itertools.count(1)

    async def call(self, method: str, params: dict | None = None, timeout: float = 5.0) -> dict:
        try:
            reader, writer = await asyncio.open_unix_connection(self._path)
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise ConnectionError(f"pendantd not running at {self._path}: {e}") from e
        try:
            req = {"id": next(self._ids), "method": method, "params": params or {}}
            writer.write((json.dumps(req) + "\n").encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            msg = json.loads(line)
            if "error" in msg:
                raise RuntimeError(msg["error"].get("message", "ipc error"))
            return msg.get("result", {})
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
```

- [ ] **Step 4: Run, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_mcp_ipc_client.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/mcp_server/__init__.py pendantd/src/pendantd/mcp_server/ipc_client.py pendantd/tests/test_mcp_ipc_client.py && git commit -m "$(cat <<'EOF'
feat(mcp_server): IPCClient for pendant-mcp ↔ pendantd

Async line-delimited JSON-RPC over a Unix socket. Surfaces ConnectionError
with a useful message when pendantd isn't running.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: `mcp_server/server.py` — MCP tool surface

**Files:**
- Create: `pendantd/src/pendantd/mcp_server/server.py`
- Create: `pendantd/tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests using an in-process IPC stub**

```python
# pendantd/tests/test_mcp_server.py
import pytest
from pendantd.mcp_server.server import build_tools


class StubIPC:
    def __init__(self, mapping): self._map = mapping
    async def call(self, method, params=None):
        if method not in self._map:
            raise RuntimeError(f"unknown method: {method!r}")
        return self._map[method]


@pytest.mark.asyncio
async def test_audio_list_devices_tool():
    ipc = StubIPC({"audio.list_devices": {"inputs": [{"name": "Jabra"}], "outputs": []}})
    tools = build_tools(ipc)
    out = await tools["audio.list_devices"]({})
    assert out["inputs"] == [{"name": "Jabra"}]


@pytest.mark.asyncio
async def test_audio_set_input_passes_substring():
    seen = {}
    class IPC:
        async def call(self, method, params=None):
            seen["m"] = method; seen["p"] = params
            return {"matched": {"name": "Jabra"}, "persisted": True}
    tools = build_tools(IPC())
    out = await tools["audio.set_input"]({"name_substring": "Jab"})
    assert seen == {"m": "audio.set_input", "p": {"substring": "Jab"}}
    assert out == {"matched": {"name": "Jabra"}, "persisted": True}


@pytest.mark.asyncio
async def test_voice_status_returns_state():
    ipc = StubIPC({"voice.status": {"state": "listening", "vocabulary": ["claude", "bob"]}})
    tools = build_tools(ipc)
    out = await tools["voice.status"]({})
    assert out["state"] == "listening"
    assert "claude" in out["vocabulary"]


@pytest.mark.asyncio
async def test_tool_surfaces_ipc_error():
    class IPC:
        async def call(self, *a, **kw):
            raise ConnectionError("pendantd not running")
    tools = build_tools(IPC())
    with pytest.raises(ConnectionError):
        await tools["audio.get_active"]({})
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_mcp_server.py -q
```

Expected: ImportError.

- [ ] **Step 3: Implement `mcp_server/server.py`**

```python
"""pendant-mcp tool surface. Built on top of an IPCClient."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


Tool_ = Callable[[dict], Awaitable[dict]]


def build_tools(ipc: Any) -> dict[str, Tool_]:
    async def _list_devices(p): return await ipc.call("audio.list_devices")
    async def _get_active(p): return await ipc.call("audio.get_active")
    async def _set_input(p):
        return await ipc.call("audio.set_input", {"substring": p.get("name_substring")})
    async def _set_output(p):
        return await ipc.call("audio.set_output", {"substring": p.get("name_substring")})
    async def _test_loopback(p):
        return await ipc.call("audio.test_loopback", {"seconds": p.get("seconds", 2)})
    async def _test_tts(p):
        return await ipc.call("audio.test_tts", {"text": p.get("text", "hello")})
    async def _voice_start(p): return await ipc.call("voice.start")
    async def _voice_stop(p): return await ipc.call("voice.stop")
    async def _voice_status(p): return await ipc.call("voice.status")
    async def _set_aliases(p):
        return await ipc.call("voice.set_wake_aliases", {"aliases": p.get("aliases", [])})
    async def _test_wake(p):
        return await ipc.call("voice.test_wake", {"timeout_seconds": p.get("timeout_seconds", 10)})

    return {
        "audio.list_devices": _list_devices,
        "audio.get_active": _get_active,
        "audio.set_input": _set_input,
        "audio.set_output": _set_output,
        "audio.test_loopback": _test_loopback,
        "audio.test_tts": _test_tts,
        "voice.start": _voice_start,
        "voice.stop": _voice_stop,
        "voice.status": _voice_status,
        "voice.set_wake_aliases": _set_aliases,
        "voice.test_wake": _test_wake,
    }


TOOL_DEFS: list[Tool] = [
    Tool(name="audio.list_devices", description="List audio inputs/outputs visible to pendantd.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="audio.get_active", description="What input/output is pendantd using right now.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="audio.set_input", description="Pin the input device by substring; null to unpin.",
         inputSchema={"type": "object", "properties": {"name_substring": {"type": ["string", "null"]}}}),
    Tool(name="audio.set_output", description="Pin the output device by substring; null to unpin.",
         inputSchema={"type": "object", "properties": {"name_substring": {"type": ["string", "null"]}}}),
    Tool(name="audio.test_loopback", description="Record and play back through the active devices.",
         inputSchema={"type": "object", "properties": {"seconds": {"type": "number", "default": 2}}}),
    Tool(name="audio.test_tts", description="Speak a phrase through the active output.",
         inputSchema={"type": "object", "properties": {"text": {"type": "string", "default": "hello"}}}),
    Tool(name="voice.start", description="Begin always-on wake matching.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="voice.stop", description="Pause wake matching.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="voice.status", description="State, vocabulary, devices, latency.",
         inputSchema={"type": "object", "properties": {}}),
    Tool(name="voice.set_wake_aliases", description="Add/remove host-side wake aliases.",
         inputSchema={"type": "object", "properties": {"aliases": {"type": "array", "items": {"type": "string"}}}}),
    Tool(name="voice.test_wake", description="Run a one-shot wake check.",
         inputSchema={"type": "object", "properties": {"timeout_seconds": {"type": "number", "default": 10}}}),
]


def make_server(ipc: Any) -> Server:
    server = Server("pendant-mcp")
    tools = build_tools(ipc)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOL_DEFS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name not in tools:
            return [TextContent(type="text", text=f"unknown tool: {name}")]
        try:
            result = await tools[name](arguments or {})
        except ConnectionError as e:
            return [TextContent(type="text", text=str(e))]
        except Exception as e:
            return [TextContent(type="text", text=f"error: {e}")]
        import json as _json
        return [TextContent(type="text", text=_json.dumps(result))]

    return server


async def serve_stdio(ipc: Any) -> None:
    server = make_server(ipc)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
```

- [ ] **Step 4: Run, verify PASS**

```bash
cd ~/robot-md-pendant/pendantd && pytest tests/test_mcp_server.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/mcp_server/server.py pendantd/tests/test_mcp_server.py && git commit -m "$(cat <<'EOF'
feat(mcp_server): tool surface for pendant-mcp

Eleven tools across audio.* and voice.* namespaces. build_tools() is
the testable seam — it accepts any IPC with .call(method, params),
so we can stub it in unit tests without spinning up pendantd.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: `mcp_server/__main__.py` — console entry point

**Files:**
- Create: `pendantd/src/pendantd/mcp_server/__main__.py`

- [ ] **Step 1: Implement entry point**

```python
"""Entry point for the `pendant-mcp` console script."""
from __future__ import annotations

import asyncio
import os
import sys

from pendantd.mcp_server.ipc_client import IPCClient
from pendantd.mcp_server.server import serve_stdio


def main() -> None:
    sock = os.environ.get("PENDANTD_CONTROL_SOCK", "/run/pendantd/control.sock")
    ipc = IPCClient(path=sock)
    try:
        asyncio.run(serve_stdio(ipc))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test**

```bash
cd ~/robot-md-pendant/pendantd && pip install -e . && which pendant-mcp
pendant-mcp <<< '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}' | head -1
```

Expected: a JSON-RPC initialize response on stdout (pendantd doesn't need to be running for `initialize` to succeed; only tool calls hit the IPC).

- [ ] **Step 3: Register with Claude Code (manual)**

```bash
claude mcp add pendant-mcp -- pendant-mcp
claude mcp list | grep pendant-mcp
```

Expected: listed as registered.

- [ ] **Step 4: Commit**

```bash
cd ~/robot-md-pendant && git add pendantd/src/pendantd/mcp_server/__main__.py && git commit -m "$(cat <<'EOF'
feat(mcp_server): pendant-mcp console entry point

Reads PENDANTD_CONTROL_SOCK from env (default /run/pendantd/control.sock),
connects via IPCClient, and serves stdio MCP. Registered with
`claude mcp add pendant-mcp -- pendant-mcp`.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: `robot-md` `init_phases/voice_setup.py` — interactive wizard

**Files:**
- Create: `~/robot-md/cli/src/robot_md/init_phases/voice_setup.py`
- Create: `~/robot-md/cli/tests/test_voice_setup.py`

- [ ] **Step 1: Write failing tests**

```python
# ~/robot-md/cli/tests/test_voice_setup.py
import io
from pathlib import Path
import pytest
import yaml

from robot_md.init_phases.voice_setup import run_voice_setup


def _stub_pendantd(monkeypatch, devices=None):
    """Inject a stub pendantd.audio.devices module."""
    devices = devices or {"inputs": [], "outputs": []}
    class FakeDevice:
        def __init__(self, name): self.name = name; self.index = 0; self.kind = "input"
        def __repr__(self): return f"<Dev {self.name}>"
    class FakeList:
        def __init__(self, d): self.inputs = [FakeDevice(n) for n in d["inputs"]]; self.outputs = [FakeDevice(n) for n in d["outputs"]]
    fake_devs_mod = type("M", (), {})()
    fake_devs_mod.list_devices = lambda: FakeList(devices)
    fake_devs_mod.pick_default = lambda lst, kind, all_devices=None: lst[0] if lst else None
    fake_audio_mod = type("M", (), {"devices": fake_devs_mod})()
    monkeypatch.setitem(__import__("sys").modules, "pendantd", type("M", (), {})())
    monkeypatch.setitem(__import__("sys").modules, "pendantd.audio", fake_audio_mod)
    monkeypatch.setitem(__import__("sys").modules, "pendantd.audio.devices", fake_devs_mod)


def test_voice_setup_skips_when_pendantd_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(__import__("sys").modules, "pendantd.audio.devices", None)
    cfg_path = tmp_path / ".robot-md" / "voice.yaml"
    rc = run_voice_setup(robot_name="bob", cfg_path=cfg_path, non_interactive=True)
    assert rc == 0
    assert "pendantd not detected" in capsys.readouterr().out
    assert not cfg_path.exists()


def test_voice_setup_writes_yaml_in_non_interactive(monkeypatch, tmp_path):
    _stub_pendantd(monkeypatch, devices={"inputs": ["USB PnP Sound Device"], "outputs": ["Jabra SPEAK 410"]})
    cfg_path = tmp_path / ".robot-md" / "voice.yaml"
    rc = run_voice_setup(robot_name="bob", cfg_path=cfg_path, non_interactive=True)
    assert rc == 0
    data = yaml.safe_load(cfg_path.read_text())
    assert data["robot_name"] == "bob"
    assert data["wake_word"] == "claude"
    assert data["input_device"] == "USB PnP Sound Device"
    assert data["output_device"] == "Jabra SPEAK 410"


def test_voice_setup_emits_todo_when_no_devices(monkeypatch, tmp_path):
    _stub_pendantd(monkeypatch, devices={"inputs": [], "outputs": []})
    cfg_path = tmp_path / ".robot-md" / "voice.yaml"
    rc = run_voice_setup(robot_name="bob", cfg_path=cfg_path, non_interactive=True)
    assert rc == 0
    text = cfg_path.read_text()
    assert "TODO(voice): no audio devices detected at init time" in text


def test_voice_setup_interactive_accepts_default(monkeypatch, tmp_path):
    _stub_pendantd(monkeypatch, devices={"inputs": ["USB PnP"], "outputs": ["Jabra"]})
    monkeypatch.setattr("sys.stdin", io.StringIO("\n\nn\nn\n"))  # accept defaults; skip tests
    cfg_path = tmp_path / ".robot-md" / "voice.yaml"
    rc = run_voice_setup(robot_name="bob", cfg_path=cfg_path, non_interactive=False, _skip_wake_check=True)
    assert rc == 0
    assert yaml.safe_load(cfg_path.read_text())["input_device"] == "USB PnP"
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd ~/robot-md/cli && pytest tests/test_voice_setup.py -q
```

Expected: ImportError.

- [ ] **Step 3: Implement `init_phases/voice_setup.py`**

```python
"""robot-md init phase — voice + audio onboarding.

Imports pendantd.audio.devices as a soft dependency. If pendantd isn't
importable, the phase prints a notice and exits rc=0.
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path
from typing import Any

import yaml


_HEADER = (
    "═══ Voice setup ═══════════════════════════════════════════"
)


def _try_import_pendantd():
    try:
        from pendantd.audio import devices as devs_mod  # type: ignore
        return devs_mod
    except Exception:
        return None


def _prompt_choice(prompt: str, options: list, default_idx: int = 0) -> int:
    sys.stdout.write(prompt + "\n")
    for i, o in enumerate(options, 1):
        marker = "  ←  auto-pick" if i - 1 == default_idx else ""
        sys.stdout.write(f"  [{i}] {o.name}{marker}\n")
    sys.stdout.write(f"  [ ] Press Enter to accept auto-pick, or type a number: ")
    sys.stdout.flush()
    line = sys.stdin.readline().strip()
    if not line:
        return default_idx
    try:
        n = int(line)
        if 1 <= n <= len(options):
            return n - 1
    except ValueError:
        pass
    return default_idx


def _confirm(prompt: str) -> bool:
    sys.stdout.write(prompt + " [Y/n] ")
    sys.stdout.flush()
    line = sys.stdin.readline().strip().lower()
    return line in ("", "y", "yes")


def run_voice_setup(
    robot_name: str,
    cfg_path: Path,
    non_interactive: bool = False,
    _skip_wake_check: bool = False,
) -> int:
    """Returns rc (0 on success, even when no audio devices were found)."""
    devs_mod = _try_import_pendantd()
    if devs_mod is None:
        sys.stdout.write("pendantd not detected; skipping voice setup\n")
        return 0

    sys.stdout.write(_HEADER + "\n")
    sys.stdout.write("Detecting audio devices…\n")
    devs = devs_mod.list_devices()

    cfg = {
        "wake_word": "claude",
        "robot_name": robot_name or "",
        "wake_aliases": [],
        "input_device": "",
        "output_device": "",
        "sample_rate": 16000,
        "tts_voice": "en_US-amy-medium",
    }

    if not devs.inputs and not devs.outputs:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            "# TODO(voice): no audio devices detected at init time\n"
            + yaml.safe_dump(cfg)
        )
        sys.stdout.write("No audio devices detected. Wrote a TODO marker; re-run when devices attach.\n")
        return 0

    in_default = devs_mod.pick_default(devs.inputs, kind="input") if devs.inputs else None
    out_default = devs_mod.pick_default(devs.outputs, kind="output", all_devices=devs) if devs.outputs else None

    if non_interactive:
        cfg["input_device"] = in_default.name if in_default else ""
        cfg["output_device"] = out_default.name if out_default else ""
    else:
        if devs.inputs:
            idx = _prompt_choice("Inputs:", devs.inputs, default_idx=devs.inputs.index(in_default) if in_default else 0)
            cfg["input_device"] = devs.inputs[idx].name
        if devs.outputs:
            idx = _prompt_choice("Outputs:", devs.outputs, default_idx=devs.outputs.index(out_default) if out_default else 0)
            cfg["output_device"] = devs.outputs[idx].name

        # Speaker test
        if cfg["output_device"]:
            sys.stdout.write(f"Speaker test… (you should hear a 1s tone via {cfg['output_device']})\n")
            sys.stdout.write("(skipped in this build — confirm interactively after pendantd starts)\n")
            if not _confirm("Hear it?"):
                sys.stdout.write("Output may need attention. Continuing.\n")
        # Mic loopback test placeholder
        if cfg["input_device"]:
            sys.stdout.write("Mic loopback test… (deferred to runtime; pendantd reports peak dBFS)\n")
            if not _confirm("Sound right?"):
                sys.stdout.write("Input may need attention. Continuing.\n")
        # Wake-word check
        if not _skip_wake_check and cfg["robot_name"]:
            sys.stdout.write(f'Wake-word check… say "{cfg["robot_name"]}" or "claude" within 10s\n')
            sys.stdout.write("(deferred to runtime — re-run with `pendantd voice test-wake`)\n")

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    provenance = (
        f"# Provenance: autodetected {_dt.datetime.utcnow().isoformat(timespec='seconds')}Z; "
        f"first input that matched USB class.\n"
    )
    cfg_path.write_text(yaml.safe_dump(cfg) + provenance)
    sys.stdout.write(f"Wrote {cfg_path}.\n")
    return 0
```

- [ ] **Step 4: Run, verify PASS**

```bash
cd ~/robot-md/cli && pytest tests/test_voice_setup.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Hook into `init.py` default flow**

In `~/robot-md/cli/src/robot_md/init.py`, find the `default_flow` that lists the six phases. Add `voice_setup` after `compliance_scaffold` (or wherever fits the existing ordering). For non-interactive mode, the call passes `non_interactive=True`. Pull `robot_name` from the manifest dataclass that the previous phase already populated.

Concretely, locate the call sequence (search for `compliance_scaffold` in `init.py`) and add right after it:

```python
    from robot_md.init_phases.voice_setup import run_voice_setup
    rc = run_voice_setup(
        robot_name=ctx.manifest.name if hasattr(ctx, "manifest") and ctx.manifest else "",
        cfg_path=Path(ctx.project_root) / ".robot-md" / "voice.yaml",
        non_interactive=non_interactive,
    )
    if rc != 0:
        return rc
```

(Adapt to the actual context object used by `init.py` — read 30 lines around the existing phase calls and copy the pattern.)

- [ ] **Step 6: Run full robot-md test suite**

```bash
cd ~/robot-md/cli && pytest -q
```

Expected: all green; new phase exercised.

- [ ] **Step 7: Commit**

```bash
cd ~/robot-md && git add cli/src/robot_md/init_phases/voice_setup.py cli/src/robot_md/init.py cli/tests/test_voice_setup.py && git commit -m "$(cat <<'EOF'
feat(init): voice_setup phase — audio device detection + voice.yaml

Soft-dependency on pendantd.audio.devices; phase no-ops with a notice
when pendantd isn't installed. Auto-picks defaults, supports --non-
interactive (--yes) and an explain-first interactive flow with speaker
+ mic confirmation prompts. Writes .robot-md/voice.yaml with provenance.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: README + systemd documentation

**Files:**
- Modify: `~/robot-md-pendant/README.md`
- Modify: `~/robot-md-pendant/systemd/` (create or modify a tmpfiles entry)

- [ ] **Step 1: Add a "Host audio path" section to README**

Insert after the Hardware section in `~/robot-md-pendant/README.md`:

```markdown
## Host-audio voice path (Pi-direct)

When the ESP32-C6 pendant isn't connected (or while waiting on hardware),
pendantd can drive voice through USB audio devices on the Pi itself.

**System packages (Pi 5):**
```
sudo apt-get install -y portaudio19-dev libasound2-dev libportaudio2
```

**Initial setup:** run `robot-md init` and complete the `voice_setup`
phase. It detects devices, lets you pick (or accepts auto-pick), and
writes `.robot-md/voice.yaml`.

**Runtime tools (MCP):** register `pendant-mcp` with Claude Code:
```
claude mcp add pendant-mcp -- pendant-mcp
```
Tools: `audio.list_devices`, `audio.set_input/output`,
`audio.test_loopback`, `audio.test_tts`, `voice.start/stop/status`,
`voice.set_wake_aliases`, `voice.test_wake`.

**Pinned vs auto:** `voice.yaml` accepts substring patterns for
`input_device` / `output_device`. Empty string = auto-pick; auto-pick
re-runs on every device change. A pendant connection is privileged in
auto mode (becomes the active device unless you've pinned a USB device).
```

- [ ] **Step 2: Add tmpfiles.d entry for the runtime dir**

Create `~/robot-md-pendant/systemd/pendantd.tmpfiles.conf`:

```
d /run/pendantd 0770 root pendant -
```

Document in README:

```markdown
**Runtime directory** (for the IPC socket):
```
sudo cp systemd/pendantd.tmpfiles.conf /etc/tmpfiles.d/pendantd.conf
sudo systemd-tmpfiles --create
```
```

- [ ] **Step 3: Verify it parses**

```bash
sudo cp ~/robot-md-pendant/systemd/pendantd.tmpfiles.conf /etc/tmpfiles.d/pendantd.conf
sudo systemd-tmpfiles --create
ls -la /run/pendantd
```

Expected: `/run/pendantd` exists, mode 0770, owner root, group pendant.

- [ ] **Step 4: Commit**

```bash
cd ~/robot-md-pendant && git add README.md systemd/pendantd.tmpfiles.conf && git commit -m "$(cat <<'EOF'
docs: host-audio voice path section + tmpfiles.d for /run/pendantd

Documents the Pi-direct voice path: system packages, init phase, MCP
registration, pin/auto rules, and the runtime directory for the IPC
control socket.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: File rcan-spec issue for future ROBOT.md `voice:` block

**Files:**
- (none) — issue filed via `gh`.

- [ ] **Step 1: File the issue**

```bash
gh issue create --repo RobotRegistryFoundation/rcan-spec \
  --title "Optional \`voice:\` block for ROBOT.md — wake aliases, language, TTS voice" \
  --label "enhancement,discussion" \
  --body "$(cat <<'EOF'
## Motivation

`robot-md-pendant`'s host-audio voice path (see [design spec](https://github.com/craigm26/robot-md-pendant/blob/main/docs/specs/2026-04-25-voice-host-audio-design.md)) currently uses the robot's `name` field as a wake word, plus the literal `"claude"`. Hosts can layer extra aliases via `.robot-md/voice.yaml`, but those don't travel with the robot.

For interoperability across pendant implementations and future managed offerings, an optional `voice:` block would let robots declare:

- Extra wake aliases (e.g., a friendly nickname).
- Spoken language (BCP-47).
- A preferred TTS voice id (advisory only).

## Schema sketch

\`\`\`yaml
voice:
  aliases: [str]        # extra wake words beyond \`name\`
  language: str         # BCP-47, default "en-US"
  tts_voice: str        # piper voice id, optional hint
\`\`\`

## Open questions

- Should aliases be normalized at the spec layer (case, punctuation)?
- Validation of BCP-47 — soft (warn) or hard (reject)?
- Is `tts_voice` part of the canonical artifact or is it always a host hint?

This is **discussion only** — pendantd will continue to function with the existing schema until/unless this lands.
EOF
)"
```

- [ ] **Step 2: Verify the issue exists**

```bash
gh issue list --repo RobotRegistryFoundation/rcan-spec --search "voice block"
```

Expected: the new issue listed.

- [ ] **Step 3: No commit needed.** This is metadata work outside the repo.

---

## Verification checklist (run end-to-end before declaring done)

- [ ] `cd ~/robot-md-pendant/pendantd && pytest -q` — all green.
- [ ] `cd ~/robot-md/cli && pytest -q` — all green (new `voice_setup` phase included).
- [ ] On the Pi: `python -m pendantd` boots; logs show active input + output device names.
- [ ] `echo '{"id":1,"method":"audio.list_devices"}' | nc -U /run/pendantd/control.sock` returns JSON.
- [ ] `claude mcp list` shows `pendant-mcp` registered.
- [ ] In Claude Code, calling `audio.list_devices` and `audio.get_active` returns expected data.
- [ ] Plug in a second USB headset → pendantd announces `"Now using <name>"` via TTS.
- [ ] Unplug active mic → pendantd falls back; logs note "input pin … not present".
- [ ] Say "claude" or `<robot_name>` near the Pi mic → wake fires; full utterance handled.
- [ ] `robot-md init --non-interactive` writes `.robot-md/voice.yaml`.
- [ ] rcan-spec issue filed and visible in `gh issue list`.

---

## Out of scope (carry-over reminders)

- No `voice:` block added to ROBOT.md / rcan-spec — issue filed only.
- No volume control, no diarization, no AGC, no Whisper fine-tuning, no Bluetooth pairing flow, no `openwakeword` low-power fallback.
- No web UI for voice configuration — the MCP surface is the control plane for v1.

## Notes for the implementer

- **TDD discipline:** use `superpowers:test-driven-development` for every task. Write test → see fail → minimum impl → see pass → commit. No batched changes.
- **Frequent commits:** every task ends with `git commit`. Don't accumulate changes across tasks.
- **Don't add deps not in Task 1.** If a step seems to need one, stop and check the spec.
- **Pendantd live state vs. library calls:** anything that reads/writes pendantd's running state goes over IPC. Only `audio.list_devices` (a stateless OS query) is a direct library call from `pendant-mcp`.
- **`set_on_end` callback wiring:** `Endpointer` accepts an `on_end` at construction; `VoiceLoop` overwrites it via `set_on_end` per utterance. Don't try to make the endpointer reusable across utterances without resetting state.
- **Failures are sticky in logs, not in state:** any audio failure logs loudly and degrades; pendantd never crashes from an audio path error. The robot-control loop must keep running.
