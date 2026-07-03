# mcp-chaos

[![CI](https://github.com/SmartAI/mcp-chaos/actions/workflows/ci.yml/badge.svg)](https://github.com/SmartAI/mcp-chaos/actions/workflows/ci.yml)

**Find out what your AI agent does when its tools fail — before production does.**

![One injected timeout costs a real agent 4 blind retries, 12 turns, 89 seconds, $1.01 — replay of a recorded Claude Code run](docs/demo.gif)

*Real recorded run: one injected `write_file` timeout vs. headless Claude Code — 4 blind
retries, 12 turns, 89 s, $1.01 burned. [Full experiment →](docs/experiments/2026-07-03-claude-code-timeout.md)*

mcp-chaos is a transparent MCP proxy that breaks your agent's tools on purpose —
timeouts, rate limits, empty or poisoned results — and hands you a report of how
the agent behaved, with a deterministic verdict (no LLM judging). Evals test the
happy path; observability shows the wreckage afterward; this is the missing
pre-ship check for **behavior under failure**.

**Zero integration cost: change one line of MCP config.** No SDK, no code, no
framework lock-in — it sits at the protocol layer, so it works with every MCP
client: Claude Code, Cursor, Claude Desktop, or anything you built yourself.

What the report tells you:

- **What one dead tool costs you** — retries, wall-clock time, dollars burned.
- **Whether your agent loops, or blindly re-runs writes** — the pattern that
  double-charges cards and double-merges PRs.
- **Whether it follows poisoned tool results** — indirect prompt injection.
- **Where your context leaks even when nothing fails** — run with zero faults
  and it profiles any MCP server: token cost of tool definitions, dead tools,
  per-tool latency and schema friction.
- **Your agent can run the whole test itself** — we ship an
  [agent skill](skills/mcp-chaos/SKILL.md): ask it to "chaos-test my MCP setup".

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
