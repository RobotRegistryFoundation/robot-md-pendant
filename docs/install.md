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

## Verify

`systemctl --user status pendantd` — should show active (running) with a log line `pendantd listening on 0.0.0.0:8765`.
