"""Record & replay cassettes: hermetic tool mocks from a recorded session.

A cassette is a JSONL file of agent-visible responses captured by the proxy —
real, faulted, or mutated alike, so a replay reproduces exactly what the agent
saw. `mcp-chaos replay` then serves it as a standalone stdio MCP server:
deterministic, zero-cost CI runs and a dev-time cache, no real server needed.

Lookup rules, all deterministic:

- tools/call matches on (tool, argument hash): FIFO through the recorded
  responses for that exact call, then the last one repeats (agents often call
  a tool more times than the recording did). A call never recorded gets an
  honest JSON-RPC error, not a guess.
- every other method falls back to method-level matching when the exact params
  differ — initialize/tools/list params vary by client and don't change the
  answer.
- ping is always answered; notifications get no reply.
"""

from __future__ import annotations

import hashlib
import json


def call_key(method: str, params: dict | None) -> str:
    """Stable hash of what identifies a request: arguments for tools/call
    (the tool name is keyed separately), full params otherwise."""
    params = params or {}
    subject = params.get("arguments") if method == "tools/call" else params
    dumped = json.dumps(subject, sort_keys=True)
    return hashlib.md5(dumped.encode()).hexdigest()[:8]


class CassetteWriter:
    """Appends one entry per response, as the agent saw it.

    Append mode for the same reason as the event recorder: clients may restart
    the proxy mid-session and truncating would wipe the cassette so far.
    """

    def __init__(self, path: str):
        self._file = open(path, "a")

    def log(self, method: str, tool: str | None, key: str, response: dict) -> None:
        """`response` is the body only: {"result": ...} or {"error": ...}."""
        entry = {"method": method, "tool": tool, "key": key, "response": response}
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()


class Cassette:
    """Loaded cassette with FIFO/sticky-last lookup state."""

    def __init__(self, entries: list[dict]):
        self._queues: dict[tuple, list[dict]] = {}
        self._last: dict[tuple, dict] = {}
        self._method_last: dict[str, dict] = {}
        for e in entries:
            k = (e["method"], e.get("tool"), e["key"])
            self._queues.setdefault(k, []).append(e["response"])
            self._method_last[e["method"]] = e["response"]

    @classmethod
    def load(cls, path: str) -> "Cassette":
        entries = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return cls(entries)

    def reply(self, msg: dict) -> dict | None:
        """Build the JSON-RPC response for one client message, or None."""
        req_id = msg.get("id")
        if req_id is None:
            return None  # notification
        method = msg.get("method", "")
        params = msg.get("params") or {}
        tool = params.get("name") if method == "tools/call" else None
        body = self._next(method, tool, call_key(method, params))
        if body is None and method == "ping":
            body = {"result": {}}
        if body is None:
            if method == "tools/call":
                message = f"mcp-chaos replay: no recorded response for tools/call {tool}"
            else:
                message = f"mcp-chaos replay: no recorded response for {method}"
            body = {"error": {"code": -32000, "message": message}}
        return {"jsonrpc": "2.0", "id": req_id, **body}

    def _next(self, method: str, tool: str | None, key: str) -> dict | None:
        k = (method, tool, key)
        queue = self._queues.get(k)
        if queue:
            body = queue.pop(0)
            self._last[k] = body
            return body
        if k in self._last:
            return self._last[k]  # exhausted: repeat the final recorded response
        if method != "tools/call":
            return self._method_last.get(method)
        return None


def serve(cassette: Cassette, in_stream, out_stream) -> None:
    """Speak stdio JSON-RPC, answering every request from the cassette."""
    for line in in_stream:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        response = cassette.reply(msg)
        if response is not None:
            out_stream.write(json.dumps(response) + "\n")
            out_stream.flush()
