# mcp-chaos

**Find out what your AI agent does when its tools fail — before production does.**

![One injected timeout costs a real agent 4 blind retries, 12 turns, 89 seconds, $1.01 — replay of a recorded Claude Code run](docs/demo.gif)

*Real recorded run: one injected `write_file` timeout vs. headless Claude Code — 4 blind
retries, 12 turns, 89 s, $1.01 burned. [Full experiment →](docs/experiments/2026-07-03-claude-code-timeout.md)*

## What you get

Your agent works when everything works. Production is different: tools time out,
APIs rate-limit, results come back empty, truncated, or poisoned. Most production
agent incidents come from **tool-call failures, not model quality** — and nothing
in your stack tests that before you ship.

`mcp-chaos` is a transparent proxy that sits between your agent and its MCP tools,
injects the failures you choose, and gives you a report with evidence:

- **What one dead tool costs you** — retries, wall-clock time, dollars burned
  (the run above: $1.01 for a single timeout).
- **Whether your agent loops** — runaway-retry detection, deterministic, no
  LLM judging.
- **Whether it retries write operations blindly** — the unsafe pattern that
  double-charges cards and double-merges PRs when a timeout wasn't real.
- **How it handles poisoned results** — inject adversarial text into tool
  output and see if your agent follows it.

**Zero integration cost.** No SDK, no code, no framework lock-in. You change one
line in your agent's MCP config — that's the whole setup. Works with every MCP
client: Claude Code, Cursor, Claude Desktop, or anything you built yourself.

## How it works

```
Agent (Claude Code / Cursor / yours)
        │  MCP
        ▼
   ┌───────────┐    faults.yaml: timeout, 429, garbage JSON,
   │ mcp-chaos │◄── empty results, slow drip, injected text
   └───────────┘
        │  MCP
        ▼
   Real MCP server (GitHub, filesystem, DB, ...)
```

The proxy relays MCP traffic untouched, except tool calls that match your fault
rules. Every event is recorded to a JSONL log and rendered as a single-file HTML
report with a resilience verdict.

## Quickstart

```bash
# 1. Describe the faults to inject
cat > faults.yaml <<'EOF'
server:
  command: "npx -y @modelcontextprotocol/server-filesystem /tmp/demo"
faults:
  - tool: "write_file"
    type: timeout
EOF

# 2. In your agent's MCP config, replace the real server with the proxy
#    (it launches the real server itself — see server.command above):
#    "command": "uvx",
#    "args": ["--from", "git+https://github.com/SmartAI/mcp-chaos", "mcp-chaos",
#             "run", "-c", "/abs/path/faults.yaml", "--record", "/abs/path/run.jsonl"]

# 3. Use your agent normally, then render the report
uvx --from git+https://github.com/SmartAI/mcp-chaos mcp-chaos report run.jsonl -o report.html
```

**[→ Full setup guide](docs/usage.md)** — copy-paste configs for Claude Code,
Cursor, and Claude Desktop, the complete fault reference, and how to read the report.

## Fault types

| Fault | What it simulates |
|---|---|
| `timeout` | Tool hangs / network death |
| `error` | 5xx / service unavailable |
| `rate_limit` | 429 with retry-after |
| `slow` | Degraded latency |
| `empty` | 200 OK with no data |
| `corrupt` | Malformed / truncated output |
| `inject` | Adversarial text in tool results (indirect prompt injection) |

Faults match by tool name (globs like `search_*` work), call count, and
probability — so you can fail the third call only, or 10% of calls, or
everything a tool ever does.

## Honest scope

The proxy sees MCP tool traffic, not the agent's chat output. It directly
observes retries, loops, and give-up behavior. Detecting "the agent told the
user it succeeded while the tool actually failed" requires transcript
correlation — that's on the roadmap, not in the box today.

Current transport: stdio MCP servers (the common case for local tools).
Streamable HTTP proxying is planned.

## Status

Pre-alpha, moving fast. Validated against a real agent (see the experiment linked
under the demo). Star/watch to follow; issues and fault-scenario ideas welcome.

## License

MIT
