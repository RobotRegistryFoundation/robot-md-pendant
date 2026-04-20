"""Minimal MCP server for tests. Implements initialize, tools/list, tools/call."""
import json, sys

def respond(req_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
    sys.stdout.flush()

def main():
    for line in sys.stdin:
        req = json.loads(line)
        method = req.get("method")
        if method == "initialize":
            respond(req["id"], {"capabilities": {"tools": {}}, "protocolVersion": "2024-11-05", "serverInfo": {"name": "mock", "version": "0.0.1"}})
        elif method == "tools/list":
            respond(req["id"], {"tools": [
                {"name": "execute_capability", "description": "", "inputSchema": {"type": "object"}},
                {"name": "estop",              "description": "", "inputSchema": {"type": "object"}},
            ]})
        elif method == "tools/call":
            params = req["params"]
            if params["name"] == "estop":
                respond(req["id"], {"content": [{"type": "text", "text": "ok"}]})
            elif params["name"] == "execute_capability":
                cap = params["arguments"].get("capability")
                respond(req["id"], {"content": [{"type": "text", "text": f"{cap}:done"}]})
            else:
                respond(req["id"], {"content": [{"type": "text", "text": "unknown"}], "isError": True})

if __name__ == "__main__":
    main()
