"""Entry point for the `pendant-mcp` console script."""
from __future__ import annotations

import asyncio
import os
import sys

from pendantd.mcp_server.ipc_client import IPCClient
from pendantd.mcp_server.server import serve_stdio


def main() -> None:
    sock = os.environ.get("PENDANTD_CONTROL_SOCK", "/run/pendantd/control.sock")
    ipc = IPCClient(path=sock)
    try:
        asyncio.run(serve_stdio(ipc))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
