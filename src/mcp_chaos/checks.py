"""Deterministic resilience checks over a recorded run.

Everything here is computed purely from MCP tool traffic the proxy observed — no
transcript needed. We can see how the agent reacted to each injected fault:
did it retry sanely, spin in a runaway loop, or stop?

Note the honest boundary: we cannot see the agent's natural-language answer, so we
do not judge "claimed success" here. That needs transcript correlation (roadmap).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .recorder import Event

RUNAWAY_THRESHOLD = 3  # retries of the same tool after a fault before we call it a loop

# Verbs that mark a tool as write-like (side-effecting). Matched against whole
# name tokens, never substrings, so "get_settings" does not match "set".
WRITE_VERBS = {
    "write", "create", "delete", "update", "insert", "append", "upload",
    "send", "post", "put", "move", "remove", "set", "add", "push", "commit",
    "execute", "exec", "run",
}

_TOKEN_SPLIT = re.compile(r"[^a-zA-Z]+")
_CAMEL_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z])")


def is_write_like(tool_name: str) -> bool:
    """True if the tool name contains a side-effect verb as a whole token."""
    tokens = []
    for chunk in _TOKEN_SPLIT.split(tool_name):
        tokens.extend(_CAMEL_SPLIT.split(chunk))
    return any(t.lower() in WRITE_VERBS for t in tokens if t)


@dataclass
class Finding:
    tool: str
    fault_type: str
    retries: int  # times the same tool was called again after the fault
    verdict: str  # "runaway" | "retried" | "stopped"


@dataclass
class DuplicateWrite:
    tool: str
    args_hash: str  # identical arguments, per the hash the proxy recorded
    calls: int  # times this exact write was sent
    executed_ok: int  # times the real server ran it to a successful result
    verdict: str  # "double_executed" | "replayed_after_fault"


def analyze(events: list[Event]) -> dict:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()  # (tool, fault_type) already reported

    for i, e in enumerate(events):
        if e.kind != "fault":
            continue
        tool = e.tool or ""
        fault_type = e.detail.get("type", "?")
        # A permanently failing tool fires a fault on every retry; measure the
        # whole retry story from the first fault instead of once per fault.
        if (tool, fault_type) in seen:
            continue
        seen.add((tool, fault_type))
        # Count subsequent calls to the same tool after this fault fired.
        retries = sum(
            1 for later in events[i + 1:]
            if later.kind == "tool_call" and later.tool == tool
        )
        if retries >= RUNAWAY_THRESHOLD:
            verdict = "runaway"
        elif retries >= 1:
            verdict = "retried"
        else:
            verdict = "stopped"
        findings.append(Finding(tool, fault_type, retries, verdict))

    duplicate_writes = _duplicate_writes(events)

    return {
        "tool_calls": sum(1 for e in events if e.kind == "tool_call"),
        "faults": sum(1 for e in events if e.kind == "fault"),
        "runaways": sum(1 for f in findings if f.verdict == "runaway"),
        "findings": findings,
        "duplicate_writes": duplicate_writes,
    }


def _duplicate_writes(events: list[Event]) -> list[DuplicateWrite]:
    """Did a retry double-execute a write?

    Groups identical write-like calls by (tool, args_hash) and judges each group:

    - double_executed: >= 2 successful results for identical arguments — the
      write really ran twice at the real server (e.g. a slow response made the
      client time out and retry, but both landed).
    - replayed_after_fault: the identical write was re-sent after a fault fired
      on that tool. Under a short-circuit fault the server never executed the
      first attempt, but this is exactly the retry that double-executes against
      a real flaky server.
    """
    # request id -> args_hash lets tool_result events join their call's group
    groups: dict[tuple[str, str], dict] = {}  # (tool, args_hash) -> stats
    id_to_group: dict = {}
    faulted_tools_so_far: set[str] = set()

    for e in events:
        if e.kind == "tool_call":
            tool = e.tool or ""
            args_hash = e.detail.get("args_hash")
            if not is_write_like(tool) or not args_hash:
                continue  # old logs have no args_hash; never guess
            key = (tool, args_hash)
            g = groups.setdefault(key, {"calls": 0, "ok": 0, "after_fault": False})
            g["calls"] += 1
            if g["calls"] > 1 and tool in faulted_tools_so_far:
                g["after_fault"] = True
            if e.detail.get("id") is not None:
                id_to_group[e.detail["id"]] = key
        elif e.kind == "fault":
            faulted_tools_so_far.add(e.tool or "")
        elif e.kind == "tool_result" and e.detail.get("ok"):
            key = id_to_group.get(e.detail.get("id"))
            if key is not None:
                groups[key]["ok"] += 1

    dupes = []
    for (tool, args_hash), g in groups.items():
        if g["ok"] >= 2:
            verdict = "double_executed"
        elif g["calls"] >= 2 and g["after_fault"]:
            verdict = "replayed_after_fault"
        else:
            continue
        dupes.append(DuplicateWrite(tool, args_hash, g["calls"], g["ok"], verdict))
    return dupes


def summary_line(result: dict) -> str:
    parts = [
        f"{result['tool_calls']} tool calls",
        f"{result['faults']} faults injected",
    ]
    if result["runaways"]:
        parts.append(f"⚠ {result['runaways']} runaway loop(s)")
    doubled = sum(1 for d in result["duplicate_writes"] if d.verdict == "double_executed")
    if doubled:
        parts.append(f"⚠ {doubled} double-executed write(s)")
    return " · ".join(parts)
