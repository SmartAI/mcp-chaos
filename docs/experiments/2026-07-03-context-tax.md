# Context-tax survey: what 7 popular MCP servers cost before the agent does anything

**Date:** 2026-07-03 · **Method:** mcp-chaos in pure-relay mode (`faults: []`),
speaking `initialize` + `tools/list` through the proxy and reading the captured
`tools_list` event. No LLM involved — this measures the tool definitions every
session loads into the agent's context before the first turn. Token figures are
the chars/4 estimate the efficiency profile uses throughout.

Run on **two machines** with identical results (byte-identical `tools/list`
payloads): macOS 26.5 / arm64 / node v26.4.0, and Fedora 43 / x86_64 / node
v22.22.2 (proxy installed there via `uvx --from git+…`, validating the Linux
path end-to-end). The measurement is deterministic and platform-independent, as
it should be — the cost is a property of the server, not the environment.

## The survey

| Server | Tools | ~Tokens per session | ~Tokens per tool |
|---|---|---|---|
| `@playwright/mcp` | 23 | **4,365** | 190 |
| `@modelcontextprotocol/server-filesystem` | 14 | **3,068** | 219 |
| `@modelcontextprotocol/server-memory` | 9 | 2,463 | 274 |
| `@modelcontextprotocol/server-everything` | 12 | 1,457 | 121 |
| `@upstash/context7-mcp` | 2 | 1,163 | 581 |
| `@modelcontextprotocol/server-sequential-thinking` | 1 | 1,137 | **1,137** |
| `mcp-server-fetch` | 1 | 287 | 287 |
| **All seven together** | **62** | **≈13,940** | — |

## What it shows

1. **The tax is invisible and it compounds.** None of these servers is doing
   anything wrong individually — but wire all seven into one agent (a normal
   power-user config) and every single session starts ~14k tokens deep before
   the first user message. At frontier-model prices that's real money on every
   turn 1, and it's context the model can't spend on your task.

2. **Cost per tool varies 9×.** `server-everything` spends ~121 tokens per tool;
   `sequential-thinking` spends 1,137 tokens on its *single* tool. Verbose
   descriptions are a design choice with a measurable price — this is the number
   MCP server authors should be watching.

3. **Most of the tax buys nothing on a given task.** A companion agent run
   (headless Claude Code / Haiku, $0.097) against the filesystem server used
   **3 of its 14 tools** — `write_file`, `read_text_file`,
   `list_allowed_directories` — leaving 11 definitions (~79% of that server's
   tax) unused. The efficiency report names them, so trimming your config is a
   checklist, not archaeology. Raw run:
   [2026-07-03-context-tax.fs-run.jsonl](2026-07-03-context-tax.fs-run.jsonl).

## Caveats, honestly

- Token counts are chars/4 estimates, not tokenizer output — good for ranking
  and orders of magnitude, not for billing math.
- Real clients may transform tool definitions before they reach the model
  (prefixing, schema re-rendering), so the model-facing count differs by
  client; the relative ranking should hold.
- Dead-weight percentages are task-dependent by nature: 11/14 unused is one
  small task, not a universal constant. Run your own workload through the
  profile to get *your* number — that's the point of the tool.

## Reproduce it

```bash
# any server, one command, no agent needed — then read the report
cat > profile.yaml <<'EOF'
server:
  command: "npx -y @playwright/mcp"
faults: []
EOF
# point your agent (or just an initialize+tools/list probe) at the proxy,
# then: mcp-chaos report run.jsonl -o report.html
```

Raw data: [local (macOS)](2026-07-03-context-tax.local.json) ·
[remote (Fedora)](2026-07-03-context-tax.remote.json).
