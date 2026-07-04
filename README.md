# mcp-chaos

[![CI](https://github.com/SmartAI/mcp-chaos/actions/workflows/ci.yml/badge.svg)](https://github.com/SmartAI/mcp-chaos/actions/workflows/ci.yml)

**Find out what your AI agent does when its tools fail — before production does.**

![One injected timeout costs a real agent 4 blind retries, 12 turns, 89 seconds, $1.01 — replay of a recorded Claude Code run](docs/demo.gif)

*Real recorded run: one injected `write_file` timeout vs. headless Claude Code — 4 blind
retries, 12 turns, 89 s, $1.01 burned. [Full experiment →](docs/experiments/2026-07-03-claude-code-timeout.md)*

**The error is obvious. Your agent's reaction isn't — and the reaction is what
costs you.** Everyone knows tools fail; what nobody can tell you is what *your*
agent does next: retry twice and move on, hammer the dead tool until the bill
runs up, re-run a payment that actually landed, follow instructions someone hid
in a tool result — or tell your user "done". The same injected timeout produced
a $0.04 graceful stop on one model and a $2.28 runaway on another (real runs —
50× apart). And you can't observe any of this in production ahead of time:
real failures are rare, random, and only visible after they've cost you.

mcp-chaos is chaos engineering for AI agents: a transparent MCP proxy that makes
tool failures happen **deterministically** — the exact tool, call, and failure
mode you choose — records the agent's reaction, and judges it with auditable
rules (no LLM judging). **Zero integration cost: change one line of MCP config.**
No SDK, no code, no framework lock-in — it sits at the protocol layer, so it
works with every MCP client: Claude Code, Cursor, Claude Desktop, or anything
you built yourself.

## Capabilities

| Capability | The question it answers | Status |
|---|---|---|
| Fault injection — 7 types: `timeout`, `error`, `rate_limit`, `slow`, `empty`, `corrupt`, `inject` | What does one dead, degraded, or poisoned tool do to your agent? | ✅ shipped |
| Deterministic resilience verdicts + `--fail-on` exit code | Does it loop? Blind-retry writes? Gate CI on the answer | ✅ shipped |
| MCP efficiency profile (zero-fault mode) | Context-token cost of tool definitions, dead tools, per-tool latency, schema friction | ✅ shipped |
| Append-safe JSONL recording → single-file HTML report | Evidence you can read, share, and audit | ✅ shipped |
| [Agent skill](skills/mcp-chaos/SKILL.md) | Your agent runs the whole test itself: "chaos-test my MCP setup" | ✅ shipped |
| Record & replay | Hermetic tool mocks: deterministic, zero-cost CI runs and a dev-time cache | 📋 planned |
| Transcript correlation | Did the agent claim success while the tool failed? | 📋 planned |
| Duplicate-write detection | Did a timeout retry double-execute a write? | 📋 planned |
| MCP config doctor | Do your servers launch, collide, or bloat your context — before the agent runs? | 📋 planned |
| Streamable HTTP transport | Hosted MCP servers (GitHub, Sentry, ...) | 📋 planned |

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

# 2. In your agent's MCP config, replace the real server with the proxy:
#    "command": "uvx",
#    "args": ["mcp-chaos", "run", "-c", "/abs/faults.yaml", "--record", "/abs/run.jsonl"]

# 3. Use your agent normally, then render the report
uvx mcp-chaos report run.jsonl -o report.html
```

## Learn more

**→ [Project page](https://smartai.github.io/mcp-chaos/)** — the cross-agent
benchmark (one timeout, six models, a 50× cost spread), how it works, fault
types, profile mode, and report screenshots.

- [Usage guide](docs/usage.md) — copy-paste configs per client, the full fault
  reference, CI gating with `--fail-on`, how to read the report
- [Example scenarios](examples/) · [Experiments](docs/experiments/) ·
  [Contributing](CONTRIBUTING.md)

## Honest scope

The proxy sees MCP tool traffic (stdio servers today), not the agent's chat
output. Detecting "the agent claimed success while the tool failed" needs
transcript correlation — on the roadmap, not in the box.

Pre-alpha, moving fast. Star/watch to follow; issues and fault-scenario ideas
welcome.

## License

MIT
