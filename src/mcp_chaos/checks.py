"""Deterministic resilience checks over a recorded run.

Everything here is computed purely from MCP tool traffic the proxy observed — no
transcript needed. We can see how the agent reacted to each injected fault:
did it retry sanely, spin in a runaway loop, or stop?

Note the honest boundary: we cannot see the agent's natural-language answer, so we
do not judge "claimed success" here. That needs transcript correlation (roadmap).
"""

from __future__ import annotations

from dataclasses import dataclass

from .recorder import Event

RUNAWAY_THRESHOLD = 3  # retries of the same tool after a fault before we call it a loop


@dataclass
class Finding:
    tool: str
    fault_type: str
    retries: int  # times the same tool was called again after the fault
    verdict: str  # "runaway" | "retried" | "stopped"


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

    return {
        "tool_calls": sum(1 for e in events if e.kind == "tool_call"),
        "faults": sum(1 for e in events if e.kind == "fault"),
        "runaways": sum(1 for f in findings if f.verdict == "runaway"),
        "findings": findings,
    }


def summary_line(result: dict) -> str:
    parts = [
        f"{result['tool_calls']} tool calls",
        f"{result['faults']} faults injected",
    ]
    if result["runaways"]:
        parts.append(f"⚠ {result['runaways']} runaway loop(s)")
    return " · ".join(parts)
