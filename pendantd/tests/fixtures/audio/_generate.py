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
