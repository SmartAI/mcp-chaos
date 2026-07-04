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
| Record & replay | Hermetic tool mocks: deterministic, zero-cost CI runs and a dev-time cache | ✅ shipped |
| Transcript correlation — `mcp-chaos correlate` | Did the agent claim success while the tool failed? | ✅ shipped |
| Duplicate-write detection + `--fail-on duplicate-write` | Did a timeout retry double-execute a write? | ✅ shipped |
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

## Benchmark: one timeout, 12 models, 5 runs each

We injected the **same** permanent `write_file` timeout into 12 models across 8
vendors, each behind an identical [minimal reference agent](benchmarks/) (no
scaffolding, so the behavior is the model's), 5 runs apiece — 60 runs, $1.09
total. No run could truly succeed; the fault kills `write_file` for good.

| Model | Runaway rate | Avg retries | Never answered | False success | Avg cost |
|---|---|---|---|---|---|
| meta-llama/llama-4-maverick | 0% | 0.0 | 0% | 0/5 | $0.0015 |
| mistralai/mistral-large-2512 | 0% | 0.2 | 0% | **1/5** | $0.0011 |
| qwen/qwen3-235b-a22b-2507 | 0% | 1.0 | 0% | **1/5** | $0.0015 |
| openai/gpt-5.1 | **0%** | 1.4 | 0% | 0/5 | $0.0041 |
| x-ai/grok-4.3 | 20% | 2.0 | 0% | 0/5 | $0.0103 |
| openai/gpt-5-mini | 80% | 2.8 | 0% | 0/5 | $0.0050 |
| moonshotai/kimi-k2.6 | 80% | 4.0 | 80% | 0/5 | $0.0127 |
| google/gemini-3-flash-preview | 100% | 3.8 | 100% | 0/5 | $0.0107 |
| deepseek/deepseek-v4-flash | 100% | 4.2 | 100% | 0/5 | $0.0020 |
| anthropic/claude-haiku-4.5 | 100% | 4.8 | 60% | 0/5 | $0.0459 |
| z-ai/glm-5 | 100% | 4.8 | 100% | 0/5 | $0.0064 |
| anthropic/claude-sonnet-5 | 100% | 5.0 | 100% | 0/5 | $0.1175 |

**What one dead tool reveals** — none of which a correctness eval would catch,
because on a working tool all twelve pass:

- **Retry discipline is a stable model trait that splits the field.** Four models
  never looped across 5 runs; five looped on every run. gpt-5.1 held 0% runaway
  every time; sonnet-5, gemini-3-flash, deepseek and glm-5 went runaway 5/5.
- **Two models lied.** mistral-large and qwen3-235b each reported "Task
  SUCCEEDED" on 1 of 5 runs — over a sandbox their own tool call had shown empty.
  The claimed-success bug is a ~20% rate in two models, not a one-off.
- **"0% runaway" can be a trap.** llama and mistral score 0% by *giving up
  instantly* (0–0.2 retries, sometimes with the wrong diagnosis) — the opposite
  of gpt-5.1's disciplined 0%. Read runaway rate together with the other columns.
- **Cost of one failure spans ~100×** ($0.0011 → $0.1175) and says nothing about
  handling it well: the priciest behavior and one of the cheapest are both bugs.

**N=5 — rough rates, not a precise ranking.** Same fault, minimal harness (real
clients scaffold more), one task type.
[Full method, per-run logs and caveats →](docs/experiments/2026-07-03-openrouter-n5.md)

## Learn more

**→ [Project page](https://smartai.github.io/mcp-chaos/)** — the full benchmark,
how it works, fault types, profile mode, and report screenshots.

- [Usage guide](docs/usage.md) — copy-paste configs per client, the full fault
  reference, CI gating with `--fail-on`, how to read the report
- [Example scenarios](examples/) · [Experiments](docs/experiments/) ·
  [Contributing](CONTRIBUTING.md)

## Honest scope

The proxy sees MCP tool traffic (stdio servers today), not the agent's chat
output. `mcp-chaos correlate` closes that gap when you hand it the transcript
(a Claude Code session `.jsonl` or the final answer as text) — the proxy alone
still can't see what the agent told your user, and the success/failure language
rules are deliberately simple and auditable, not NLP.

Pre-alpha, moving fast. Star/watch to follow; issues and fault-scenario ideas
welcome.

## License

MIT
