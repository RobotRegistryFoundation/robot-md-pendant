# firmware v0.1 Hardware Proof Checklist

Run before tagging v0.1. Assumes `pendantd` is running on the Pi (systemd active, MCP server pointed at a valid `ROBOT.md`).

## Setup

- Pi at `ws://<pi-ip>:8765`
- ESP32-C6 pendant USB-C → Pi USB port
- SO-ARM101 connected to Pi (separate `/dev/ttyACM*` — NOT the pendant's)
- OAK-D connected (thumbnail path not in MVP; included for visual debug if desired)

## Flashing notes (hardware-specific)

The Waveshare board's CH343 USB-UART bridge does **not** wire DTR/RTS to the C6's EN/BOOT pins — auto-reset via `esptool` fails with "No serial data received". Two paths:

1. **First flash** requires the manual bootloader entry sequence on the physical tactile buttons (`Key1`/`Key3` per schematic; identify which is BOOT by trial). Hold BOOT, tap RESET, release BOOT.
2. **Subsequent flashes** use the ESP32-C6's native USB Serial/JTAG (enabled in `sdkconfig.defaults` via `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y`). After first flash, the pendant exposes a native-USB `/dev/ttyACM*` (separate from the CH343). Use:
   ```
   idf.py -p /dev/ttyACM<N> --before usb-reset flash monitor
   ```
   where `<N>` is the native USB port (check `dmesg` for `303a:1001` Espressif USB JTAG/serial device).

## Checks

- [ ] **First-boot provisioning**:
  - [ ] `idf.py erase-flash` → flash → boot
  - [ ] UART prompts for SSID/PSK/Pi URL
  - [ ] Reboots into Connecting screen

- [ ] **Wi-Fi + WebSocket**:
  - [ ] Connects to Wi-Fi within 15s
  - [ ] Connects to Pi WS, receives `hello`
  - [ ] Dashboard renders with buttons from pendantd's `buttons.yaml`

- [ ] **Preset buttons**:
  - [ ] "Home" tap → arm homes; tool_call events appear in chat pane
  - [ ] "Pick" tap → arm picks; tool_call events visible

- [ ] **Chat (text)**:
  - [ ] Tap textarea → LVGL keyboard appears
  - [ ] Type a prompt, press enter → Claude responds in chat pane

- [ ] **PTT voice in**:
  - [ ] Hold mic button, say "home the arm", release
  - [ ] pendantd logs show transcript; arm homes

- [ ] **Voice out**:
  - [ ] Claude's reply plays audibly through the onboard speaker

- [ ] **Soft-stop**:
  - [ ] Tap STOP → `[STOPPED]` banner paints **immediately** (before any network roundtrip)
  - [ ] Pi-side MCP `estop` fires; pendantd logs confirm

- [ ] **Heartbeat + reconnect**:
  - [ ] Kill pendantd → pendant shows "Pi unreachable"
  - [ ] Restart pendantd → pendant reconnects within ~5s, shows Dashboard
  - [ ] Unplug Wi-Fi → pendant shows Connecting → reconnects when Wi-Fi returns

- [ ] **Barge-in**:
  - [ ] During a long TTS reply, hold mic → playback stops; new recording starts; Pi logs show `barge_in`

## Known limits (not tested in MVP)

- JPEG thumbnail rendering (not implemented — v0.1.1)
- Wake-word continuous audio streaming (not implemented — v0.1.1)
- AP-fallback captive portal (deferred to v0.2)
- BLE provisioning (deferred to v0.3)
- Battery operation (wall-powered only)
- Long-duration soak testing (defer)

## Post-checklist

If all boxes green: `git tag firmware-v0.1 && git push --tags`. Announce.
