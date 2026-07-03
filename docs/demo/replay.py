#!/usr/bin/env python3
"""Replay of the recorded 2026-07-03 run for the README demo GIF.

Every event, timestamp, and cost figure is real, taken from
docs/experiments/2026-07-03-claude-code-timeout.{md,run.jsonl}.
Wall-clock gaps are compressed (~6x) so the GIF stays short.

Usage: python3 replay.py [--fast]   (--fast skips sleeps, for testing)
"""

import sys
import time

FAST = "--fast" in sys.argv

R = "\033[31m"    # red
G = "\033[32m"    # green
Y = "\033[33m"    # yellow
C = "\033[36m"    # cyan
D = "\033[2m"     # dim
B = "\033[1m"     # bold
X = "\033[0m"     # reset


def sleep(s):
    if not FAST:
        time.sleep(s)


def out(line="", pause=0.0):
    print(line, flush=True)
    sleep(pause)


def typed(cmd, pause=0.6):
    print(f"{D}${X} ", end="", flush=True)
    sleep(0.4)
    for ch in cmd:
        print(ch, end="", flush=True)
        sleep(0.02)
    print(flush=True)
    sleep(pause)


# ── intro ────────────────────────────────────────────────────────────────
out(f"{B}mcp-chaos{X} — break your agent's tools on purpose, before production does", 1.6)
out()

# ── the one-file config ──────────────────────────────────────────────────
typed("cat faults.yaml")
out(f"{D}server:{X}")
out(f"{D}  command:{X} \"npx -y @modelcontextprotocol/server-filesystem /tmp/demo\"")
out(f"{D}faults:{X}")
out(f"  - {D}tool:{X} \"write_file\"")
out(f"    {D}type:{X} {R}timeout{X}", 1.8)
out()
typed('claude -p "create status.txt using the fs tools ..."   # any MCP agent', 1.0)
out()

# ── recorded traffic (real timestamps from the run log) ─────────────────
out(f"{D}── recorded MCP traffic · Claude Code × filesystem server · replayed ~6x ──{X}", 1.2)

EVENTS = [
    # (t, label, ok, note)
    (12.4, "tools/call write_file", False, "injected: timeout"),
    (22.2, "tools/call write_file", False, "injected: timeout   ← blind retry #1"),
    (28.9, "tools/call read_text_file", True, "agent double-checks"),
    (38.4, "tools/call list_allowed_directories", True, ""),
    (43.0, "tools/call write_file", False, "injected: timeout   ← retry #2"),
    (52.1, "tools/call write_file", False, "injected: timeout   ← retry #3"),
    (56.7, "tools/call list_directory", True, ""),
    (66.1, "tools/call edit_file", True, "workaround attempt (ENOENT)"),
    (72.1, "tools/call write_file", False, "injected: timeout   ← retry #4"),
    (76.6, "tools/call get_file_info", True, "gives up"),
]

prev = 8.0
for t, label, ok, note in EVENTS:
    sleep(min((t - prev) / 6.0, 1.6))
    prev = t
    mark = f"{G}✓{X}" if ok else f"{R}✗{X}"
    color_note = f"{D}{note}{X}" if ok else f"{R}{note}{X}"
    out(f" {D}{t:5.1f}s{X}  {mark} {label:<38} {color_note}")

sleep(1.4)

# ── verdict (analyzer output + measured cost) ────────────────────────────
out()
out(f"{B}mcp-chaos report{X} run.jsonl")
sleep(0.8)
out(f" {Y}⚠ VERDICT: runaway{X} — write_file · timeout · {B}4 retries{X} of a dead tool")
sleep(0.8)
out(f"   one injected fault cost the agent: {B}12 turns · 89 s · $1.01{X}", 2.4)
out()
out(f"{C}uvx mcp-chaos run -c faults.yaml{X}  {D}·{X}  zero agent code  {D}·{X}  github.com/SmartAI/mcp-chaos", 3.5)
