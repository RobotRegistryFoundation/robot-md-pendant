from __future__ import annotations

import asyncio


class Whisper:
    def __init__(self, command: list[str]) -> None:
        self._command = command

    async def transcribe(self, pcm_s16le_16k_mono: bytes) -> str:
        proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate(pcm_s16le_16k_mono)
        return stdout.decode("utf-8", errors="ignore")
