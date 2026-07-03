"""Deterministic MCP-efficiency metrics over a recorded run.

Everything is computed from traffic the proxy observed — no LLM judging. Token
figures are the chars/4 heuristic: rough, but stable and good enough to rank
where context is going. Injected faults never reach these stats: short-circuited
calls produce `fault` events, and only real server responses become
`tool_result` events.
"""

from __future__ import annotations

from .recorder import Event

CHARS_PER_TOKEN = 4


def profile(events: list[Event]) -> dict:
    listing: Event | None = None
    for e in events:
        if e.kind == "tools_list":
            listing = e  # last one wins; clients may re-list mid-session

    tools: dict[str, dict] = {}

    def stats(name: str) -> dict:
        return tools.setdefault(name, {
            "calls": 0, "errors": 0, "avg_ms": 0, "result_tokens": 0,
            "corrected_retries": 0, "_ms": [], "_chars": 0,
        })

    call_hash: dict = {}  # request id -> args_hash
    pending_error: dict[str, str | None] = {}  # tool -> args_hash of the errored call

    for e in events:
        if e.kind == "tool_call" and e.tool:
            s = stats(e.tool)
            s["calls"] += 1
            call_hash[e.detail.get("id")] = e.detail.get("args_hash")
            if e.tool in pending_error:
                if e.detail.get("args_hash") != pending_error.pop(e.tool):
                    s["corrected_retries"] += 1
        elif e.kind == "tool_result" and e.tool:
            s = stats(e.tool)
            s["_ms"].append(e.detail.get("ms", 0))
            s["_chars"] += e.detail.get("chars", 0)
            if not e.detail.get("ok", True):
                s["errors"] += 1
                pending_error[e.tool] = call_hash.get(e.detail.get("id"))

    for s in tools.values():
        if s["_ms"]:
            s["avg_ms"] = round(sum(s["_ms"]) / len(s["_ms"]))
        s["result_tokens"] = s.pop("_chars") // CHARS_PER_TOKEN
        del s["_ms"]

    advertised = listing.detail.get("tools", []) if listing else None
    return {
        "has_data": listing is not None or any(e.kind == "tool_result" for e in events),
        "advertised": len(advertised) if advertised is not None else None,
        "listing_tokens": (listing.detail.get("chars", 0) // CHARS_PER_TOKEN) if listing else 0,
        "unused": sorted(set(advertised) - set(tools)) if advertised else [],
        "tools": tools,
    }
