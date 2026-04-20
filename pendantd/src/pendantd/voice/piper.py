from __future__ import annotations
import asyncio
from typing import AsyncIterator


class Piper:
    def __init__(self, command: list[str]) -> None:
        self._command = command
        self._proc: asyncio.subprocess.Process | None = None

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        self._proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(text.encode())
        self._proc.stdin.close()
        while True:
            chunk = await self._proc.stdout.read(2048)
            if not chunk:
                break
            yield chunk

    async def cancel(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                self._proc.kill()
