# robot-md-pendant

> Touchscreen + voice pendant for [`robot-md`](https://github.com/RobotRegistryFoundation/robot-md)-declared robots.
> ESP32-C6 AMOLED frontend, Python service on the Pi, Claude Agent SDK + [`robot-md-mcp`](https://github.com/RobotRegistryFoundation/robot-md-mcp) on the backend.

**Status:** early design. See [`docs/specs/2026-04-20-design.md`](docs/specs/2026-04-20-design.md) for the v0.1 spec. Implementation plan + code to follow.

## What it is

A $35 Waveshare ESP32-C6 Touch AMOLED 1.8" becomes a portable remote for any `ROBOT.md`-declared robot. Three ways to drive the robot from the pendant:

- **Tap** — a configurable grid of preset buttons (Home, Pick, Release, …).
- **Speak** — push-to-talk or a custom "Claude" wake word; Whisper transcribes, Claude plans, `robot-md-mcp` executes.
- **Type** — a small chat pane for freeform prompts.

A dashboard on the same screen shows live robot state: last vision detection, current pose, a 2fps camera thumbnail, and a prominent soft-stop button. A heartbeat watchdog on the Pi halts the arm if the pendant disappears.

## Where this fits in the stack

| Layer | Piece | What it is |
|---|---|---|
| Declaration | [ROBOT.md](https://github.com/RobotRegistryFoundation/robot-md) | The file a robot ships at its root. |
| Agent bridge | [robot-md-mcp](https://github.com/RobotRegistryFoundation/robot-md-mcp) | MCP server exposing ROBOT.md tools. |
| **Pendant** ← *this* | **robot-md-pendant** | Touchscreen + voice frontend that drives the above through the Claude Agent SDK. |
| Runtime | [OpenCastor](https://github.com/craigm26/OpenCastor) | Reference open-source runtime. |

## Hardware

- **Pendant:** Waveshare ESP32-C6 Touch AMOLED 1.8" (onboard mic + speaker; Wi-Fi 6 + BLE5; RISC-V single core).
- **Host:** Raspberry Pi 5 (Pi 4 possible but voice latency increases).
- **Robot:** any robot with a valid `ROBOT.md` and a `robot-md-mcp`-compatible driver. Initial target: SO-ARM101.

## License

Apache-2.0.
