# firmware (ESP32-C6) — v0.1 Design

> **Status:** Draft, pending author review. Created 2026-04-20.
>
> **Scope:** MVP firmware for the Waveshare ESP32-C6-Touch-AMOLED-1.8 pendant. Talks to the Pi-side [`pendantd`](2026-04-20-design.md#components) over WebSocket using the protocol schemas at `schemas/v1/`.
>
> **Sibling spec:** [`2026-04-20-design.md`](2026-04-20-design.md) (the project-level v0.1 design). This doc fleshes out the firmware section of that spec for the concrete C6 hardware.
>
> **Related plan:** Plan A (`pendantd` v0.1) has shipped to main. Plan B (this firmware) will follow after spec approval.

---

## Summary

Fresh ESP-IDF v5.5.1 project targeting `esp32c6`. Boots into a three-task FreeRTOS architecture (UI / net / audio), brings up the SH8601 AMOLED over QSPI, drives the ES8311 codec for mic + speaker, connects via Wi-Fi STA to the Pi-side `pendantd`, and renders what it tells us.

Memory is the dominant constraint — the C6 has ~400KB SRAM with **no PSRAM** on this variant. LVGL v9 runs in partial-render mode with two ~30KB tile buffers; the AMOLED's internal GRAM holds the full frame. Anything non-essential is deferred (AP fallback, BLE provisioning, wake-word audio path, JPEG thumbnails, OTA) to keep the footprint down and ship fast.

**User-visible behavior:**
- Power on → wait for Wi-Fi → "Pi unreachable" or Dashboard.
- Dashboard: status strip, chat pane (last 5 messages), button grid from Pi's `buttons.yaml`, mic PTT button, big red soft-stop.
- Tap a preset button → robot does the thing; tool_call progress shows live.
- Hold mic → speak → release → Pi transcribes → Claude replies → speaker plays the answer.
- Tap soft-stop → immediate [STOPPED] banner + Pi halts arm.

---

## Hardware (confirmed from Waveshare demo repo)

| Part | Role | Interface |
|---|---|---|
| **ESP32-C6FH4** | MCU | RISC-V single-core, 160MHz, ~400KB SRAM, 4–8MB flash, no PSRAM |
| **SH8601** | 368×488 AMOLED controller | QSPI — SPI2_HOST; CS=GPIO5, PCLK=GPIO0 |
| **FT5x06** | Capacitive touch | I2C |
| **TCA9554** | I/O expander | I2C @ 0x20 (LCD_RST, LCD_BL, speaker amp enable on pin 7) |
| **ES8311** | Mono audio codec | I2C + I2S (MCK=19, BCK=20, DIN=21, WS=22, DOUT=23) |
| **AXP2101** | PMIC | I2C (battery charging, rails) |
| **QMI8658** | 6-axis IMU | I2C (unused in v0.1) |
| **PCF85063** | RTC | I2C (unused in v0.1) |
| **microSD** | Storage | SPI (MOSI=10, SCK=11, MISO=18, CS=6) — unused in v0.1 but available |

**Known porting sidebar:** Waveshare's `sdkconfig.defaults` in the LVGL example has `CONFIG_IDF_TARGET="esp32s3"` and enables octal SPIRAM — inherited from their S3 board. Task 1 of Plan B fixes this: change target to `esp32c6`, remove `CONFIG_SPIRAM*`, adjust `CONFIG_FREERTOS_HZ`/`CONFIG_ESP_MAIN_TASK_STACK_SIZE` as needed.

**Mic count note:** Waveshare's product description says "dual digital microphones array" but the demo code + schematic header show a single ES8311 mono codec. We start with mono (plenty for Whisper) and verify against the schematic PDF during Task 1. If a second mic exists, it's a v0.1.1 enhancement.

---

## Architecture

```
 ┌─────────────────────────── ESP32-C6 @ 160MHz (no PSRAM) ───────────────────────┐
 │                                                                                │
 │  FreeRTOS tasks:                                                               │
 │   ui_task    (prio 3, 8KB stack)  — LVGL tick/flush, touch, event dispatch     │
 │   net_task   (prio 5, 6KB stack)  — Wi-Fi, WebSocket, heartbeat, JSON          │
 │   audio_task (prio 6, 4KB stack)  — I2S DMA rx+tx, 20ms PCM chunks             │
 │                                                                                │
 │  Queues:                                                                       │
 │   inbox_q  (32 msgs)  net → ui/audio                                           │
 │   outbox_q (64 msgs)  ui/audio → net                                           │
 │                                                                                │
 │  Shared state (app_state_t, behind a mutex):                                   │
 │   connection_state, wifi_state, robot_status, buttons[], chat_history[]        │
 │                                                                                │
 │  Memory strategy:                                                              │
 │   LVGL v9 partial-render, 2×30KB tile buffers (double-buffered)                │
 │   QSPI pushes tiles to SH8601 internal GRAM                                    │
 │   I2S DMA: 8KB rx + 8KB tx                                                     │
 │   WS receive buffer: 16KB                                                      │
 │   TLS OFF for v0.1 — LAN only                                                  │
 │                                                                                │
 └────────────────────────────────────────────────────────────────────────────────┘
            ▲                     ▲                         ▲
       QSPI │                I2C+GPIO                I2S + I2C
            ▼                     ▼                         ▼
       SH8601 AMOLED         FT5x06 + TCA9554          ES8311 → mic & spk
```

**Principles (inherit Plan A):**
- **Dumb pendant.** Renders state pushed by Pi, sends user intent, runs no robot logic.
- **Zero-friction first.** Serial provisioning for v0.1 (AP+captive portal is v0.2, BLE provisioning is v0.3).
- **Task isolation.** Each task owns its hardware; communicate via queues only. No shared mutable state outside `app_state_t`.
- **Text-only status in MVP.** JPEG thumbnail decode is a v0.1.1 concern — the 1.8" screen has plenty of room for text state.

---

## Components

Project layout:

```
firmware/
├── CMakeLists.txt
├── partitions.csv              # single-app: nvs, factory (~3MB), data (~1MB)
├── sdkconfig.defaults          # esp32c6 target, LVGL sized for no-PSRAM
├── idf_component.yml           # component registry deps
├── main/
│   ├── main.c                  # boot → init → start scheduler
│   └── app_state.c             # shared state struct + mutex
├── components/
│   ├── board_hw/               # PMIC, expander, pin map, board_init()
│   ├── display_lvgl/           # SH8601 + FT5x06 + LVGL port
│   ├── wifi_mgr/               # STA, NVS creds, reconnect backoff, events
│   ├── ws_client/              # esp_websocket_client wrapper + heartbeat timer
│   ├── protocol/               # v1 message parse/emit (matches schemas/v1/)
│   ├── es8311_audio/           # codec init, I2S DMA, PCM rings
│   ├── ui/                     # LVGL screens + widgets + event dispatch
│   └── app/                    # state machine + queue glue + provisioning
└── tests/
    ├── host/                   # host-compilable unit tests (ctest)
    └── target/                 # ESP-IDF target tests (opt-in)
```

### 1. `board_hw`

Owns power-on sequencing: AXP2101 rail config, TCA9554 init (LCD_RST low→high, backlight pin, speaker amp enable pin 7 high). Exposes `esp_err_t board_init(void)`. Called once from `main()`.

### 2. `display_lvgl`

SH8601 QSPI init (SPI2_HOST, CS=GPIO5, PCLK=GPIO0), FT5x06 touch on I2C. LVGL v9 port with partial render — two 30KB tile buffers alternating. Registers `lv_display_t*` + `lv_indev_t*` (touch). Exposes `esp_err_t display_init(void)` and `void display_tick_task(void)` (runs LVGL tick in `ui_task`).

### 3. `wifi_mgr`

Reads SSID/PSK from NVS namespace `wifi`. If empty → returns `ESP_ERR_NVS_NOT_FOUND`. Otherwise connects STA with reconnect backoff (1/5/15/60s capped). Emits `WIFI_EVT_CONNECTED` / `WIFI_EVT_LOST` via `esp_event`. Exposes:
- `esp_err_t wifi_mgr_init(void)`
- `esp_err_t wifi_mgr_save_creds(const char *ssid, const char *psk)`
- `esp_err_t wifi_mgr_start(void)` (returns `ESP_ERR_NVS_NOT_FOUND` if not provisioned)

### 4. `ws_client`

Wraps `esp_websocket_client`. URL from NVS namespace `server` key `url`. Reconnect backoff 1/2/5/10s capped. 10Hz heartbeat via `esp_timer` once connected. On inbound text frame → `protocol_parse` → `inbox_q`. On inbound binary frame (`0x02` audio_out) → directly to `audio_task` via a separate audio inbox to avoid JSON overhead. Drains `outbox_q` each net_task iteration.

### 5. `protocol`

Pure C, host-compilable, matches `schemas/v1/`. Two halves:
- **Parse**: `protocol_parse(const char *json, size_t len, msg_t *out)` — returns UNKNOWN for unrecognized types (safe ignore). Uses cJSON.
- **Emit**: `protocol_emit_button_press(char *buf, size_t cap, const char *id)` etc., one per outgoing type. Returns bytes written.

All outgoing payloads stamp `"v":1`. All incoming payloads with `v != 1` are dropped.

### 6. `es8311_audio`

ES8311 codec init via I2C (uses reference `es8311.c` from the Waveshare Arduino demo, vendored as a component). I2S standard mode, 16kHz mono, 16-bit. Two 8KB DMA ring buffers (rx + tx). Exposes:
- `esp_err_t audio_init(void)`
- `void audio_start_record(void)` / `void audio_stop_record(void)` — toggles RX DMA, PCM chunks emitted as 20ms `0x01`+PCM frames to `outbox_q`.
- `void audio_play_chunk(const uint8_t *pcm, size_t n)` — enqueues inbound audio_out PCM into TX DMA ring.
- `void audio_stop_playback(void)` — for soft-stop + barge-in (flushes TX DMA).

### 7. `ui`

LVGL v9 screens + widgets. Three screens:

- **ConnectingScreen** — centered spinner, "Connecting to `<ssid>`…" label, retry count.
- **DashboardScreen** (primary):
  - Top status strip: Wi-Fi icon, robot status dot (green/yellow/red), session indicator.
  - Middle chat pane: last 5 messages (user → Claude), scrollable, auto-scrolls on new.
  - Button grid: 2×N from Pi-pushed `buttons.yaml`, scrollable if more than 6.
  - Mic PTT button (hold to record, release to send).
  - Soft-stop: big red button, bottom-right, always visible. Tap shows `[STOPPED]` banner.
- **ErrorScreen** — "Pi unreachable" banner, reconnect indicator. Auto-returns to Dashboard on WS reconnect.

Event dispatch is simple: touch event → post a typed message to `outbox_q`. Inbox messages from `app_task` trigger screen invalidation via `lv_async_call`.

### 8. `app`

The glue. `app_task` main loop: drains `inbox_q`, updates `app_state_t` under mutex, posts UI invalidations. On boot, checks NVS; if empty enters **serial provisioning** (see next section). Maps UI events (button presses, mic hold, soft-stop) to outbound messages.

---

## Serial provisioning (MVP)

First-boot flow when NVS is empty:

1. UI shows "Provisioning mode — connect USB and open serial (115200 8N1)".
2. UART prints:
   ```
   pendant: provisioning required
   pendant: SSID?
   ```
3. User types SSID (line-terminated), hits enter.
4. ```
   pendant: PSK?
   ```
5. User types PSK.
6. ```
   pendant: Pi URL? (e.g. ws://192.168.1.42:8765)
   ```
7. User types URL.
8. Firmware saves all three to NVS (`wifi:ssid`, `wifi:psk`, `server:url`) and reboots.

Zero UI code, zero web server. If the user wants to re-provision, hold the soft-stop button for 10 seconds on boot → NVS wipe + re-enter provisioning. (v0.2 replaces with AP+captive portal; v0.3 replaces with BLE provisioning.)

---

## Memory budget (rough)

| Bucket | Estimated | Notes |
|---|---|---|
| ESP-IDF core + Wi-Fi + LwIP + WebSocket | ~170KB | Standard baseline |
| LVGL v9 core + widgets + Montserrat-14 font | ~55KB | ~15% larger than v8 |
| LVGL tile buffers (2 × 30KB) | 60KB | Double-buffered partial render |
| I2S DMA (rx + tx) + audio rings | 24KB | 8KB each DMA, 8KB rings |
| WS receive buffer | 16KB | Max JSON message |
| JSON scratch + cJSON pool | 10KB | |
| Task stacks (ui 8K, net 6K, audio 4K, idle 2K) | 20KB | |
| `app_state_t` + UI state + NVS cache | 15KB | |
| **Total** | **~370KB** | of ~400KB SRAM |
| **Headroom** | **~30KB** | Tight but viable |

If we overrun during bring-up: first shrink LVGL (drop unused Montserrat sizes, disable `LV_USE_ANIMATION`), then consider v8 downgrade, then shrink chat_history from 5 to 3.

---

## Data flow

Inherited from Plan A's protocol (13 flow types in `2026-04-20-design.md` §Data flow). Pendant-side mapping:

| Flow | Pendant role |
|---|---|
| Connect / hello | net_task receives hello → app_state populated → ui switches to Dashboard |
| Heartbeat | net_task esp_timer 10Hz, no queue |
| Button press (direct_mcp/prompt) | ui tap → outbox → ws send; inbound tool_call events → ui progress on the pressed button |
| Chat (text) | ui on-screen keyboard → outbox chat_prompt; reply renders in chat pane; audio_out chunks → audio_task TX |
| Voice in (PTT) | ui mic-hold → audio_task starts RX → binary `0x01`+PCM frames to outbox every 20ms; on release → voice_state idle |
| Voice out | inbox binary `0x02` frames → audio_task TX DMA |
| Config reload (buttons) | inbox buttons → app → ui rebuilds button grid |
| Soft-stop | ui red button → outbox soft_stop → ui paints `[STOPPED]` immediately (does not wait for Pi) |
| Barge-in | ui: mic hold while speaker playing → outbox barge_in + audio_task stop_playback |

**Deferred flows (not in MVP):** voice in (wake word), thumbnail rendering, all AP/BLE provisioning paths.

---

## Error handling

Same invariant as Plan A: any error → graceful UI state + keep trying. Pendant never locks into a frozen screen.

Firmware-specific failure modes (Pi-side failures are covered in `2026-04-20-design.md`):

- **NVS empty/corrupt** → serial provisioning mode.
- **Wi-Fi STA timeout** → backoff retry; UI stays ConnectingScreen.
- **WS server unreachable** → backoff retry; "Pi unreachable" banner.
- **Invalid/unknown/oversized JSON** → log, drop, continue.
- **outbox_q / inbox_q full** → drop oldest, increment counter.
- **ES8311 init fail** → disable audio, show "Audio unavailable — text only" banner, continue.
- **I2S over/underrun** → drop chunk / inject silence.
- **Low memory** → drop non-essential draws; if persistent, eventual task watchdog reboot.
- **Task hang** → task watchdog @ 5s → `esp_restart()`.
- **Panic/stack overflow** → coredump to flash → reboot.

**Soft-stop is paint-first:** the `[STOPPED]` banner renders immediately on tap, before any network roundtrip. Redundant with Pi-side heartbeat watchdog — both fire on the same event, pendant for UX, Pi for safety.

---

## Testing

Three layers.

**1. Host-compilable unit tests (`tests/host/`)** — the `protocol/` module is pure C. CMake + ctest on dev machine. Tests: hello parse golden, every outgoing message round-trips its v1 schema, unknown types rejected safely, audio ring overflow behavior.

**2. Target unit tests (`tests/target/`)** — ESP-IDF `idf.py build -T unit-test` format. NVS state machine, queue overflow policy, ES8311 init (opt-in; requires hardware). CI builds to verify compilation; does not run.

**3. Hardware proof (`docs/hardware-proof.md`)** — manual pre-release checklist against real Pi + real C6 pendant. Walks every MVP flow: serial provisioning, STA connect, WS hello, each preset button, PTT round-trip, soft-stop, Wi-Fi drop → reconnect. Mirrors the `~/rm-v062-hw/HARDWARE-PROOF.md` style from the robot-md project.

**CI:** new workflow `.github/workflows/firmware.yml` — runs `idf.py build` for `esp32c6` + host `ctest`. Existing `.github/workflows/ci.yml` (pytest + schema smoke for Plan A) stays untouched.

**Not tested:** LVGL visual rendering (inspection only), long soak, battery/brownout electrical edge cases.

---

## Known limits & deferred work

Documented so v0.1.1+ knows what to pick up:

- **Serial provisioning only.** AP+captive portal is v0.2, BLE provisioning is v0.3.
- **No wake-word audio path.** PTT only. Pi can still run wake-word if you stream audio continuously — MVP doesn't.
- **No JPEG thumbnail rendering.** Text-only status on the 1.8" screen (which is already information-dense).
- **No OTA.** Flash via USB (`idf.py flash`).
- **No battery optimization.** Wall-powered via USB.
- **IMU + RTC unused.** Present on board, reserved for later use (gesture UI? sleep-wake-on-motion?).
- **microSD unused.** Reserved for later: wake-word models, audio debug logs, custom fonts/icons.
- **Dual mic array not confirmed.** README advertises it; demo is mono. We start mono; upgrade if schematic confirms second mic.
- **LVGL visual regression testing.** Manual only for v0.1.
- **Power sequencing.** Relies on Waveshare's reference; no custom brownout handling.

---

## Bring-up risks

Calling these out now so the implementation plan has explicit mitigation:

1. **`sdkconfig.defaults` is S3-shaped.** Task 1 fixes target + PSRAM config. Validate with `idf.py build` as the very first thing.
2. **No audio example in Waveshare IDF demos.** The Arduino demo (`15_ES8311`) shows the pin map and codec init sequence but uses Arduino-style I2S. We port to IDF's `esp_driver_i2s` — fairly straightforward but a risk spot.
3. **No Wi-Fi/WS example in Waveshare demos.** Stock ESP-IDF components cover this; no risk, just extra writing.
4. **Memory budget is tight (~30KB headroom).** Budget review after first working build. Have a shrink-LVGL fallback plan.
5. **"Dual digital microphones array" claim.** Confirm via schematic PDF in Task 1. If true, we may later switch to PDM or route the second mic to a software noise-gate.

---

## Version history

- **2026-04-20** — v0.1 draft.
