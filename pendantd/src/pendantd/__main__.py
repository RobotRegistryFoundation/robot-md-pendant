from __future__ import annotations
import asyncio
import os
from pathlib import Path

from .server import Server
from .mcp_bridge import MCPBridge
from .buttons import load_buttons

async def async_main() -> int:
    cfg_dir = Path(os.environ.get("PENDANTD_CONFIG", str(Path.home() / ".config" / "robot-md-pendant")))
    buttons = load_buttons(cfg_dir / "buttons.yaml")
    robot_md_path = os.environ["ROBOT_MD_PATH"]
    mcp = MCPBridge(command=["npx", "robot-md-mcp", "--robot", robot_md_path])
    await mcp.start()
    try:
        server = Server(host="0.0.0.0", port=8765, mcp=mcp, buttons=buttons)
        async with server.run() as addr:
            print(f"pendantd listening on {addr}")
            await asyncio.Future()  # run forever
    finally:
        await mcp.stop()

def main() -> int:
    try:
        return asyncio.run(async_main()) or 0
    except KeyboardInterrupt:
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
