# Installing pendantd on a Raspberry Pi 5

## Prerequisites
- Raspberry Pi 5 (Pi 4 works but voice latency increases)
- Python 3.11+
- Node.js 18+ (for `robot-md-mcp`)
- `whisper.cpp` with `ggml-base.en.bin` model
- `piper-tts` with a voice model (default: `en_US-lessac-medium`)
- A valid `ROBOT.md` file (see [robot-md](https://github.com/RobotRegistryFoundation/robot-md))
- Anthropic API key (`ANTHROPIC_API_KEY` env var)

## Install

```bash
pip install -e pendantd
mkdir -p ~/.config/robot-md-pendant
cp config/buttons.yaml config/voice.yaml ~/.config/robot-md-pendant/
cp systemd/pendantd.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pendantd
```

## Environment

- `PENDANTD_CONFIG` — path to config dir (default: `~/.config/robot-md-pendant`)
- `ROBOT_MD_PATH` — path to your `ROBOT.md` file (required)
- `ANTHROPIC_API_KEY` — Anthropic API key for Claude Agent SDK (required)
- `PENDANTD_SERVE_LAN=1` — same as `--serve-lan` (see below)
- `PENDANTD_TOKEN` — handshake token; generated into `<config dir>/token` if unset
- `PENDANTD_PORT` — listen port (default `8765`)

## Serving a hardware pendant on the LAN

pendantd binds `127.0.0.1:8765` by default: the websocket drives a robot, so it
is not on the network until you say so. For the ESP32 pendant, start it with
`--serve-lan` (`ExecStart=/usr/bin/python3 -m pendantd --serve-lan` in the unit
file, then `systemctl --user daemon-reload && systemctl --user restart pendantd`).

Serving on a LAN address requires a token. pendantd generates one on first run
into `~/.config/robot-md-pendant/token` (mode 0600) and logs the pendant URL:

```
ws://<pi-address>:8765/?id=<pendant-id>&token=<token>
```

Provision the pendant with that whole URL. A handshake without the token — or
with the wrong one — gets `401` and is never accepted; `?id=` is a routing
label, not an identity.

## What the STOP button reports

The pendant reports the stop it got, it does not assert a stop happened. When
the MCP server registers no stop tool, or the call fails, the status message is
`{"stop": "stop_not_confirmed", "estopped": false, "reason": ...}` and the
[STOPPED] banner stays off. A latch is never cleared by reconnecting: clearing
is an explicit `{"v":1,"type":"stop_clear","confirm":true}` message.

## Verify

`systemctl --user status pendantd` — should show active (running) with a log line
`pendantd listening on 127.0.0.1:8765` (or `0.0.0.0:8765` when started with `--serve-lan`).
