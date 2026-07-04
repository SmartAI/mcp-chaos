"""A minimal Streamable HTTP MCP server used only for tests.

Speaks just enough of the transport to exercise the relay: JSON responses,
one SSE-streamed response (a notification followed by the result), a session
id issued on initialize, and a request journal for assertions.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SESSION_ID = "sess-mock-123"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        msg = json.loads(body)
        self.server.journal.append({
            "method": msg.get("method"),
            "tool": (msg.get("params") or {}).get("name"),
            "session": self.headers.get("Mcp-Session-Id"),
        })
        req_id = msg.get("id")
        method = msg.get("method")

        if req_id is None:  # notification
            self.send_response(202)
            self.end_headers()
            return

        if method == "initialize":
            self._json({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "mock-http"}, "capabilities": {},
            }}, extra={"Mcp-Session-Id": SESSION_ID})
        elif method == "tools/list":
            self._json({"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
                {"name": "get_order", "description": "fetch an order"},
                {"name": "merge_pull_request", "description": "merge a PR"},
            ]}})
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name", "")
            result = {"content": [{"type": "text",
                                   "text": f"OK: {name} succeeded with real data"}],
                      "isError": False}
            if name == "get_order":
                # streamed: a progress notification, then the response
                self._sse([
                    {"jsonrpc": "2.0", "method": "notifications/progress",
                     "params": {"progress": 1}},
                    {"jsonrpc": "2.0", "id": req_id, "result": result},
                ])
            else:
                self._json({"jsonrpc": "2.0", "id": req_id, "result": result})
        else:
            self._json({"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32601, "message": "method not found"}})

    def _json(self, msg, extra=None):
        payload = json.dumps(msg).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _sse(self, messages):
        chunks = b"".join(f"data: {json.dumps(m)}\n\n".encode() for m in messages)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(chunks)))
        self.end_headers()
        self.wfile.write(chunks)


def start() -> tuple[ThreadingHTTPServer, str]:
    """Start on an ephemeral port; returns (server, base_url)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.journal = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/mcp"
