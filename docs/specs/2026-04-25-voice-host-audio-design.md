# robot-md-pendant — Host-Audio Voice Path Design

> **Status:** Draft, pending author review. Created 2026-04-25.
>
> **Scope:** Add a Pi-direct voice loop to `pendantd` so the operator can address Claude Code by the robot's name (from `ROBOT.md`) or the literal word "claude," using USB audio devices attached to the Raspberry Pi. Replaces the absent ESP32-C6 audio source while the pendant hardware bring-up is blocked on the stuck BOOT button (see `project_robot_md_pendant_bringup` memory). Adds a new Python MCP server (`pendant-mcp`) and a new `robot-md init` phase (`voice_setup`).
>
> **Non-goals:** changes to the rcan-spec / ROBOT.md schema (filed as a separate issue for future integration); the ESP32-C6 firmware path (kept intact and re-activates when the pendant connects); volume/AGC/diarization/multi-user; Bluetooth pairing flows.
>
> **Predecessor:** [`2026-04-20-design.md`](./2026-04-20-design.md) — pendant v0.1 design (ESP32-C6 audio source assumed). This document supplements that spec with a host-audio source that activates when no pendant is connected.

---

## Summary

`pendantd` currently owns a voice pipeline (`voice/wake.py`, `voice/whisper.py`, `voice/piper.py`, `voice/buffer.py`, `voice/endpoint.py`) that consumes PCM frames from the pendant over WebSocket. With the pendant hardware blocked, those frames never arrive — the pipeline is wired but unfed. This change introduces a **host-audio source** (USB mic + USB speaker on the Pi 5) that feeds the same pipeline, plus the surrounding device-management story:

- **Auto-detect** USB inputs and outputs at boot via `sounddevice.query_devices()`.
- **Auto-pick** sensible defaults (USB > built-in for input; headset-class > USB-out > HDMI > built-in for output).
- **Sticky overrides** in `.robot-md/voice.yaml` — substring match against device names.
- **Live device manager** — `pyudev` hot-plug events plus pendant arrival/departure hooks; switch active devices and announce via TTS.
- **Wake-word vocabulary** — `["claude", manifest.name, *aliases]`, matched against streaming `faster-whisper tiny.en` transcripts (no per-name training, no separate keyword model).
- **Interactive onboarding** — new `robot-md init` phase `voice_setup.py` detects devices, runs speaker + loopback tests, runs a live wake-word check, writes the sidecar config.
- **MCP control plane** — new Python stdio MCP server `pendant-mcp` exposes `audio.list_devices`, `audio.set_input/output`, `audio.test_loopback`, `voice.start/stop/status`, `voice.set_wake_aliases`, `voice.test_wake`.

**One-line pitch:** "Plug in a USB headset, run `robot-md init`, then say 'bob, pick up the red lego.'"

---

## Architecture

```
┌────────────────────────────── Raspberry Pi 5 ──────────────────────────────┐
│                                                                            │
│  USB mic ──► sounddevice  ──►  AudioRouter  ──►  StreamingWakeMatcher      │
│  USB spkr ◄─ sounddevice  ◄──   (active in)        (faster-whisper tiny)   │
│  (or Pendant WS PCM)                │                       │              │
│                                     ▼                       ▼              │
│                              DeviceWatcher           WakeEvent: claude|bob │
│                              (pyudev + WS hooks)            │              │
│                                                             ▼              │
│                                                       Utterance capture    │
│                                                       (VAD endpointed)     │
│                                                             │              │
│                                                             ▼              │
│                                                  voice/whisper.transcribe  │
│                                                             │              │
│                                                             ▼              │
│                                              agent.py  (Claude Agent SDK   │
│                                                  + robot-md-mcp bridge)    │
│                                                             │              │
│                                                             ▼              │
│                                                  voice/piper.py TTS  ──┐   │
│                                                                        │   │
│                              ┌──── pendant-mcp (Python) ────┐          │   │
│                              │ audio.list_devices            │         │   │
│  Claude Code (host) ────────►│ audio.set_input/output        │         │   │
│  via stdio MCP               │ audio.test_loopback           │         │   │
│                              │ voice.start/stop/status       │         │   │
│                              │ voice.set_wake_aliases        │         │   │
│                              └───────────────┬───────────────┘         │   │
│                                              │                         │   │
│                                              ▼                         │   │
│                                  IPC over /run/pendantd/control.sock ◄─┘   │
└────────────────────────────────────────────────────────────────────────────┘
```

**Process model.** `pendantd` runs as a single asyncio process under systemd. `pendant-mcp` is a separate stdio MCP server (registered with Claude Code via `claude mcp add`). It calls `pendantd.audio.devices.list_devices()` directly (a stateless OS query — safe to run from either process). All other tools — anything that reads or mutates *pendantd's* live state, or routes through *pendantd's* audio router — go over a Unix socket at `/run/pendantd/control.sock` (root-owned, mode 0660, group `pendant`). Two MCP servers register with Claude Code: `robot-md-mcp` (existing, robot-side) and `pendant-mcp` (new, voice-side).

**Sticky devices.** `.robot-md/voice.yaml` holds substring patterns for `input_device` and `output_device`. If pinned and matched, the device is sticky. If pinned and missing at boot, log a warning, fall back to auto-pick, speak a notice. If unpinned (`""`), recompute auto-pick on every device change.

---

## Components

### `pendantd/audio/` — new package

| File | Responsibility |
|---|---|
| `devices.py` | `list_devices()` returning `{inputs, outputs}`; `pick_default(kind, hint)`; `Device` dataclass; substring matcher with ambiguity warning. |
| `router.py` | `AudioRouter` — owns the active input and output streams, swaps on hot-plug, emits 16 kHz mono int16 PCM frames downstream. |
| `streams.py` | thin async wrappers over `sounddevice.InputStream` / `OutputStream`. |
| `watcher.py` | `DeviceWatcher` — `pyudev` Monitor on `subsystem=sound` (300 ms debounce) merged with `on_pendant_connect` / `on_pendant_disconnect` hooks from `server.py`. |
| `loopback.py` | `record_and_play(seconds)` for the speaker + mic test ritual. |

### `pendantd/voice/` — extends existing files

| File | Change |
|---|---|
| `wake.py` | Replaced. New `StreamingWakeMatcher` runs `faster-whisper tiny.en` on a rolling 1.5 s window every ~500 ms with `vad_filter=True`. Matches against `["claude", robot_name, *aliases]` (case-insensitive, trailing-whitespace tolerant, fuzzy edge — Levenshtein ≤ 1 on names ≥ 4 chars). |
| `endpoint.py` | Unchanged. The existing RMS-threshold `Endpointer` (300 ms trailing silence → utterance ends) is reused as-is — no `webrtcvad` dependency. |
| `loop.py` | **New.** Orchestrates: router → wake matcher → endpoint → utterance Whisper → agent → piper TTS → router. State machine: `idle` → `listening` → `thinking` → `speaking` → `listening`. Wake events during a TTS notice (≤ 600 ms) duck the notice and proceed. |
| `whisper.py`, `piper.py`, `buffer.py` | Interfaces unchanged; consumed by `loop.py`. |

### `pendantd/voice_cfg.py` — extended schema

```yaml
# .robot-md/voice.yaml
wake_word: claude              # constant (existing)
robot_name: bob                # NEW — pulled from ROBOT.md `name` at init time
wake_aliases: []               # NEW — host-side aliases (e.g. ["buddy"])
input_device: ""               # NEW — substring; "" = auto-pick
output_device: ""              # NEW — substring; "" = auto-pick
sample_rate: 16000             # NEW
tts_voice: en_US-amy-medium    # existing
```

`VoiceCfgWatcher` already live-reloads on file changes via `watchfiles` — editing the YAML reconfigures on the fly with no service restart.

### `pendantd/mcp_server/` — new package

Python stdio MCP server using the official `mcp` SDK. Exposes the tool surface described in **MCP Tool Surface**. Communicates with the running pendantd over `/run/pendantd/control.sock`.

### `robot-md/cli/src/robot_md/init_phases/voice_setup.py` — new phase

Slots into the existing six-phase `init` pipeline. Imports `pendantd.audio.devices` as a library — pendantd is a soft dependency. If pendantd isn't importable, phase prints `"pendantd not detected; skipping voice setup"` and exits with rc=0 (matches existing phase patterns that gate on hardware presence).

### Removed

- `openwakeword>=0.6` removed from `pendantd/pyproject.toml`. No longer used; wake is transcript-match.

---

## Onboarding flow

`robot-md init` (interactive):

```
═══ Voice setup ═══════════════════════════════════════════
Detecting audio devices…

Inputs:
  [1] USB PnP Sound Device (card 1)        ← auto-pick
  [2] Jabra SPEAK 410 USB
  [3] Built-in audio (bcm2835)
  [ ] Press Enter to accept auto-pick, or type a number:

Outputs:
  [1] Jabra SPEAK 410 USB                  ← auto-pick
  [2] USB PnP Sound Device (card 1)
  [3] HDMI 1
  [ ] Press Enter to accept auto-pick, or type a number:

Speaker test… (you should hear a 1s tone)
  ✓ Played 880 Hz tone via Jabra SPEAK 410.   Hear it? [Y/n] y

Mic loopback test… (say something — recording 2s)
  ✓ Recorded 32 KB. Playing back…
  Sound right? [Y/n] y

Wake-word check… say your robot's name and "claude" within 10s
  Robot name from ROBOT.md: "bob"
  ✓ Heard "bob" at 3.4s
  ✓ Heard "claude" at 6.1s

Wrote .robot-md/voice.yaml.
```

**Auto-pick rules** (`pick_default`):

1. Inputs: USB > Bluetooth A2DP > built-in.
2. Outputs: device that has both input + output channels (likely a headset) > USB-out > HDMI > built-in.
3. Skip device-list entries that are aliases of the system default to avoid duplicates.
4. The pendant WS source is not auto-picked at init time (pendant absence is the trigger for this whole feature). Pendant becomes the auto-pick at runtime when it arrives — see **Hot-plug behavior**.

**`--non-interactive` / `--yes`:**

- Auto-picks both ends silently.
- Skips speaker test, mic loopback test, wake-word check.
- Writes `.robot-md/voice.yaml` with auto-picked names.
- If zero audio devices detected: emit TODO marker `# TODO(voice): no audio devices detected at init time` and exit phase with rc=0 (matches existing phase behavior — never silently guess Tier D fields).

**Failure modes:**

- pendantd not installed → `"pendantd not detected; skipping voice setup"` + skip phase.
- `sounddevice` fails to open chosen device → log + try next candidate; if all fail, emit TODO marker.
- Wake-word check times out (10 s, no hits) → soft warning `"wake check skipped — re-run with `pendantd voice test-wake`"` + write config anyway. Same posture as not blocking on calibration when the robot is absent.
- ROBOT.md `name` field missing → wake_aliases stays empty, only `"claude"` works; phase prints a warning and proceeds.

**State written:**

```yaml
# .robot-md/voice.yaml — generated by robot-md init voice_setup phase
wake_word: claude
robot_name: bob
wake_aliases: []
input_device: "USB PnP Sound Device"      # substring match
output_device: "Jabra SPEAK 410"
sample_rate: 16000
tts_voice: en_US-amy-medium
# Provenance: autodetected 2026-04-25T19:14:02Z; first input that matched USB class.
```

---

## Hot-plug behavior

`DeviceWatcher` runs inside pendantd, two event sources merged into one stream.

**Source 1 — USB audio (pyudev):**

```python
monitor = pyudev.Monitor.from_netlink(ctx)
monitor.filter_by(subsystem='sound')
# events: 'add' / 'remove' / 'change' on /dev/snd/* nodes
```

300 ms debounce (USB enumeration fires several events per plug). Re-query `sounddevice.query_devices()` after each event; diff against previous list.

**Source 2 — pendant arrival/departure:**

The existing pendant WS server in `pendantd/server.py` is extended with two hooks: `on_pendant_connect(stream)` and `on_pendant_disconnect()`. The pendant becomes a virtual audio source/sink in `AudioRouter`, fed by WS PCM frames (the path the existing voice pipeline was designed for).

**Switching policy:**

- Pinned in `voice.yaml` → stay on the pinned device if present. If a pinned device just disappeared, fall back to auto-pick + log + speak a notice on the new output.
- Unpinned → recompute auto-pick on every device change. If the winner differs from the current device, switch + speak notice.
- **Pendant arrival is privileged:** when a pendant connects, it wins the auto-pick race even against a USB headset. Pinning a USB device explicitly overrides this — explicit beats implicit.

**Audible notices** (TTS through the *new* device):

| Event | Notice |
|---|---|
| USB headset plugged in (becomes active) | "Now using Jabra headset." |
| USB headset unplugged (was active) | "Switched to built-in audio." |
| Pendant connected | "Pendant connected." |
| Pendant disconnected | "Pendant disconnected." |

Wake events during a notice (≤ 600 ms) duck the notice and proceed normally.

**Reboot survival:** systemd unit `pendantd.service` already exists. On boot, `voice_cfg.py` loads `.robot-md/voice.yaml`; `AudioRouter` resolves substring matches against the current device list. Same fallback rules as live hot-plug. No special boot-time path.

**Edge cases:**

- Active output disappears mid-TTS: piper output stream raises; router catches, swaps device, replays the remainder if < 500 ms in (else drops).
- Input disappears mid-utterance: discard the partial utterance, log, do **not** call the agent — never act on truncated speech.
- Two USB devices with identical names: match by `sounddevice` index when substring is ambiguous; emit a warning suggesting a more unique pin.
- BlueZ A2DP devices take 1–2 s to initialize after the `add` event: 500 ms grace period before opening the stream.

---

## MCP tool surface (`pendant-mcp`)

Stdio MCP server. Registered with `claude mcp add pendant-mcp -- pendant-mcp`. Tools talk to the running pendantd over `/run/pendantd/control.sock`.

### Audio device tools

| Tool | Args | Returns | Use |
|---|---|---|---|
| `audio.list_devices` | — | `{inputs: [{id, name, channels, sample_rates, kind, active}], outputs: [...]}` | "What can I use?" |
| `audio.get_active` | — | `{input: {...}, output: {...}, source: "pinned" \| "auto"}` | "What am I using right now?" |
| `audio.set_input` | `name_substring` (or `null` to unpin) | `{matched: device_or_null, persisted: bool}` | Pin a mic; persists to `voice.yaml`. |
| `audio.set_output` | `name_substring` (or `null`) | same | Pin a speaker. |
| `audio.test_loopback` | `seconds` (default 2) | `{recorded_bytes, played: bool, peak_dbfs}` | "Can I hear myself?" |
| `audio.test_tts` | `text` (default `"hello"`) | `{played: bool, duration_ms, voice}` | Speaker check. |

### Voice loop tools

| Tool | Args | Returns | Use |
|---|---|---|---|
| `voice.start` | — | `{state: "listening"}` | Begin always-on wake matching. |
| `voice.stop` | — | `{state: "idle"}` | Pause wake matching. |
| `voice.status` | — | `{state, vocabulary, current_input, current_output, last_wake_at, last_utterance, latency_ms}` | Health/debug. |
| `voice.set_wake_aliases` | `aliases: [str]` | `{vocabulary: [...], persisted: bool}` | Add/remove host-side aliases; persists to `voice.yaml`. Does **not** touch ROBOT.md. |
| `voice.test_wake` | `timeout_seconds` (default 10) | `{matches: [{phrase, timestamp_s}]}` | Re-run the init wake check on demand. |

### Tool design notes

- Every tool is idempotent and returns observable state — no opaque "OK".
- `audio.set_*` accepts a substring. If multiple devices match, the **first match by `sounddevice` index order wins**; the matched device is reported back so the agent can confirm what it pinned. Pass `null` to unpin.
- `voice_cfg.py` `REQUIRED_KEYS` grows to include `robot_name`, `input_device`, `output_device`, `sample_rate` (with defaults supplied if missing — the watcher fills defaults rather than rejecting old configs, so existing `voice.yaml` files keep loading).
- `voice.set_wake_aliases` writes the host's `voice.yaml` only. The rcan-spec issue (below) tracks future migration of aliases into ROBOT.md.
- All results are JSON-serializable. No streaming responses — wake events are observable via `voice.status`.
- Errors return MCP `isError: true` with a one-line `text` describing the failure (e.g., `"no device matched substring 'jabra'"`).

### Deliberately NOT in v1 (YAGNI)

- Volume control (defer; piper output level is sufficient).
- Per-utterance transcript history (agent already sees its inputs).
- Wake-threshold tuning (internal knob).
- Recording/playback of arbitrary files (out of scope).

---

## Testing strategy

| Layer | Approach |
|---|---|
| `audio/devices.py` | Pure functions on a fake `query_devices()` fixture. Tests cover USB > built-in priority, substring match, ambiguous-name warning, empty-list path. |
| `audio/router.py` | Stub `InputStream` / `OutputStream` emitting pre-recorded PCM. Tests cover swap on hot-plug, mid-TTS device loss, pinned vs. auto fallback. |
| `audio/watcher.py` | Inject fake pyudev events via a queue; assert debounced output. Pendant connect/disconnect via direct hook calls. |
| `voice/wake.py` | Recorded fixtures at `pendantd/tests/fixtures/audio/{claude,bob,silence,noise}_16k.wav`. Assert match, no-match, fuzzy edge ("claud-uh"). |
| `voice/loop.py` | End-to-end with stubbed agent + stubbed piper. Assert state transitions and that wake during a TTS notice still fires. |
| `pendant_mcp/` | In-process MCP client (the SDK provides one). Each tool has a happy-path + one error-path test. |
| `init_phases/voice_setup.py` | Drive the wizard with scripted stdin; assert the YAML written matches expected. `--non-interactive` path covered. |
| Hardware smoke | `@pytest.mark.requires_audio` opt-in tests that need a real mic/speaker. CI skips them. |

---

## Dependencies

Added to `pendantd/pyproject.toml`:

```
sounddevice>=0.4
faster-whisper>=1.0
pyudev>=0.24
mcp>=1.0
```

Removed: `openwakeword>=0.6` (no longer used).

Console scripts:

```toml
[project.scripts]
pendantd = "pendantd.__main__:main"
pendant-mcp = "pendantd.mcp_server.__main__:main"
```

System packages (documented in README; not installed by Python): `portaudio19-dev`, `libasound2-dev`, `libportaudio2`. ALSA is already present on Pi 5.

---

## Error handling principles

- Audio device failures **never** crash pendantd — they degrade to "no audio" and log loudly. The robot-control loop must keep running.
- Wake-word ASR worker exception → restart with backoff, log, hold loop in `idle` until restored. Never act on partial transcripts.
- Unix socket gone (pendant-mcp can't reach pendantd) → MCP tools return `isError: true` with `"pendantd not running"`; suggest `systemctl status pendantd`.
- ROBOT.md `name` field changed at runtime → `voice_cfg.py` watcher live-reloads; new vocabulary takes effect on the next wake-match cycle (~500 ms).

---

## rcan-spec issue (filed, not implemented here)

- Repo: `continuonai/rcan-spec`
- Title: **"Optional `voice:` block for ROBOT.md — wake aliases, language, TTS voice"**
- Filed 2026-04-25 as [continuonai/rcan-spec#197](https://github.com/continuonai/rcan-spec/issues/197)
- Body: links to this design as motivation. Schema sketch:

  ```yaml
  voice:
    aliases: [str]        # extra wake words beyond `name`
    language: str         # BCP-47, default "en-US"
    tts_voice: str        # piper voice id, optional hint
  ```
- Tags: `enhancement`, `discussion`. Filed during this design phase, not waiting on PR.

---

## Out of scope (explicit YAGNI)

- Multi-user voice profiles.
- Speaker diarization ("who spoke?").
- Volume normalization / AGC.
- Custom Whisper fine-tuning.
- Wake-word confidence tuning UI.
- Bluetooth mic pairing flow (works if BlueZ already paired; pairing is out of scope).
- Voice activity logging beyond debug logs.
- A "low-power" `openwakeword` fallback (drop now; reconsider only if Pi 5 ASR cost proves unbearable).

---

## Build sequence (informational; the implementation plan will refine)

1. `pendantd/audio/devices.py` + `pendantd/audio/router.py` + tests with fake fixtures.
2. `pendantd/audio/watcher.py` with stubbed pyudev + tests.
3. Replace `voice/wake.py` with `StreamingWakeMatcher` + recorded fixture tests.
4. `voice/loop.py` orchestrator + tests.
5. Wire `voice/loop.py` into `pendantd/__main__.py`; manual smoke on Pi.
6. `pendantd/mcp_server/` package + tools + in-proc MCP client tests.
7. `robot-md` `init_phases/voice_setup.py` + scripted-stdin tests.
8. systemd unit refresh for pendantd; `pendant-mcp` registration docs in README.
9. File rcan-spec issue.

---

## Open questions

None at design time. All Q1–Q7 decisions are recorded above:

- Q1: Pendant project on Pi 5 + USB audio.
- Q2: Streaming ASR (`faster-whisper tiny.en`) + transcript wake match.
- Q3: Auto-pick + sidecar override + `--list` diagnostic.
- Q4: New Python MCP server `pendant-mcp` inside pendantd.
- Q5: No rcan-spec change for v1; file an issue for future integration.
- Q6: New `init_phases/voice_setup.py` in robot-md.
- Q7: Auto-switch with audible TTS notice; pinned devices sticky.
