# Experiment: the write executed — the agent was told "timeout"

**Date:** 2026-07-03 · **Agent:** headless Claude Code (`claude -p`, model
haiku), `MCP_TOOL_TIMEOUT=5000` · **Real server:**
`@modelcontextprotocol/server-filesystem` v0.2.0.

## Setup

A `slow` fault adds 8 s to every `write_file` call — the call still reaches
the real server; only the response is late
([config](2026-07-03-duplicate-write.faults.yaml)). The client gives up
waiting at 5 s. This is the classic non-idempotent-retry hazard: "timeout"
does not mean "didn't happen".

## What happened

The agent sent the identical `write_file` three times, saw three timeouts,
and reported ([full answer](2026-07-03-duplicate-write.answer.txt)):

```
**Failed.** The `mcp__fs__write_file` tool timed out on all three retry attempts. The fs MCP server is not responding to write requests. The allowed directory is `/private/tmp/chaos-dup`, but the operation to create `status.txt` could not be completed due to server timeouts.
```

Meanwhile, on disk:

```
$ ls -la /tmp/chaos-dup
.rw-r--r--   19 min   3 Jul 20:27  status.txt      # "deployment complete"
```

The write **landed**. The agent's world-model ("the operation could not be
completed") and the actual world (the file exists) diverged — exactly the
divergence that duplicates a payment when the tool isn't an idempotent
file write.

## The gate

```bash
uvx mcp-chaos report run.jsonl -o report.html --fail-on duplicate-write
```

Output, byte-identical to
[`2026-07-03-duplicate-write.gate.out.txt`](2026-07-03-duplicate-write.gate.out.txt),
exit code **1**:

```
mcp-chaos: wrote /tmp/chaos-dup-report.html
mcp-chaos: 4 tool calls · 3 faults injected
mcp-chaos: FAIL write_file (args eab66c28): replayed_after_fault, sent 3x, executed ok 0x
```

`replayed_after_fault` is the verdict for "an identical write was re-sent
after a fault on that tool" — the retry pattern that double-executes against
a real flaky backend. The full event log is
[`2026-07-03-duplicate-write.run.jsonl`](2026-07-03-duplicate-write.run.jsonl).

## Why `executed ok 0x`, when the file exists?

An honest limitation, found by this run: when Claude Code abandons a call it
sends an MCP cancellation, and the server SDK then suppresses its (late)
response — so the proxy never sees a success acknowledgment to count, and the
stricter `double_executed` verdict (2+ acknowledged executions of the same
write) can't trigger with this client. The filesystem proves at least one
execution anyway. `double_executed` remains reachable with clients that
time out without cancelling, or when both responses arrive late but do
arrive.

Cost of the run: one haiku session, ~$0.03.
