class AudioBuffer:
    def __init__(self) -> None:
        self._chunks: list[bytes] = []

    def append(self, chunk: bytes) -> None:
        self._chunks.append(chunk)

    def drain(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data
