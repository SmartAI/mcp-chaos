"""A minimal stdio MCP server used only for tests.

Speaks just enough JSON-RPC to answer initialize, tools/list, and tools/call.
Every tools/call returns a fixed successful text result.
"""

import json
import sys


def _send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        method, req_id = req.get("method"), req.get("id")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": req_id,
                   "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "mock"}}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
                {"name": "get_order", "description": "fetch an order"},
                {"name": "merge_pull_request", "description": "merge a PR"},
            ]}})
        elif method == "tools/call":
            name = (req.get("params") or {}).get("name", "")
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"OK: {name} succeeded with real data"}],
                "isError": False,
            }})
        elif req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": "method not found"}})


if __name__ == "__main__":
    main()
