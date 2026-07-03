---
name: mcp-chaos
description: Chaos-test any MCP-based AI agent by injecting tool-call faults (timeouts, rate limits, empty or corrupt results, adversarial prompt injection) through the mcp-chaos proxy, then report how the agent behaved. Use whenever the user wants to test an agent's resilience or reliability, see what an agent does when its tools fail, measure retry loops or the cost of tool failures, test robustness against poisoned tool results, or mentions chaos engineering, fault injection, or failure testing for agents, MCP servers, or tool calls — even if they never name mcp-chaos.
---

# Chaos-testing an agent with mcp-chaos

mcp-chaos is a transparent stdio MCP proxy: it launches the real MCP server as a
child process, relays all traffic untouched, and injects configured faults into
matching `tools/call` requests while recording every event. The agent under test
needs zero code changes — only its MCP config changes.

Run it with `uvx` (no install step):

```bash
uvx --from git+https://github.com/SmartAI/mcp-chaos mcp-chaos --version
```

If fetching from GitHub is blocked in your environment (sandbox, permission
policy) or a local checkout exists, use `--from /path/to/mcp-chaos` instead —
everything below works the same with either form.

## Workflow

### 1. Define the scenario

Ask (or infer from context): which MCP server is under test, which tool(s)
should fail, and what failure mode matters to the user. Good default scenario:
a permanent `timeout` on the server's most important *write* tool — it reveals
retry storms and unsafe blind re-runs, the two most expensive behaviors.

### 2. Write `faults.yaml`

```yaml
server:
  command: "npx -y @modelcontextprotocol/server-filesystem /tmp/chaos-demo"  # the REAL server

faults:
  - tool: "write_file"       # exact tool name or glob ("search_*", "*")
    type: timeout            # timeout | error | rate_limit | slow | empty | corrupt | inject
    # after_calls: 3         # optional: first 2 calls succeed, fail from the 3rd
    # probability: 0.1       # optional: flaky tool instead of dead tool
    # payload: "..."         # inject only: adversarial text appended to results
    # delay_ms: 5000         # slow only: added latency
```

Fault behavior the scenario design depends on:

- What the agent sees: `timeout` → JSON-RPC error "Request timed out";
  `error` → "Internal error: service unavailable"; `rate_limit` → "Rate limit
  exceeded, retry after 5s"; `empty` → a successful response with no content;
  `corrupt` → real text truncated to half; `inject` → real result + payload.
- `timeout`, `error`, `rate_limit`, `empty` **short-circuit** — the real server
  never receives the call, so they are safe on write operations and real credentials.
- `slow`, `corrupt`, `inject` **execute the real call** and tamper with the
  response — point them at test resources only.
- Rules are ordered; the first rule that fires wins, and once triggered a rule
  keeps firing (a default `timeout` rule = that tool is dead forever).
- Match by the server's own tool name (as in `tools/list`), NOT the client's
  prefixed name — `mcp__github__merge_pull_request` in Claude Code matches
  `tool: "merge_pull_request"`.

### 3. Insert the proxy into the agent's MCP config

Replace the real server's entry wherever the agent under test configures MCP
servers (`.mcp.json`, `~/.cursor/mcp.json`, `claude_desktop_config.json`, ...).
Use **absolute paths** — MCP clients pick their own working directory:

```json
{
  "mcpServers": {
    "fs": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/SmartAI/mcp-chaos", "mcp-chaos",
        "run", "-c", "/abs/path/faults.yaml", "--record", "/abs/path/run.jsonl"
      ]
    }
  }
}
```

### 4. Run the scenario

Before spending an agent run, validate the config in one command — this exits
immediately and surfaces YAML errors or a broken server command:

```bash
echo "" | uvx --from git+https://github.com/SmartAI/mcp-chaos mcp-chaos \
  run -c /abs/path/faults.yaml --record /tmp/check.jsonl
# look for: "mcp-chaos: proxying <cmd> with N fault(s)" on stderr
```

Use a **fresh `--record` path per scenario** (and never the real path for the
check above). The proxy appends to the file and never truncates it — each
launch writes a `session_start` marker — so a client that restarts the MCP
server mid-session loses nothing. The flip side is that reusing a path mixes
old runs into the new report, so pick a new file when the scenario changes.

For a self-contained test, drive a headless agent yourself rather than waiting
for an interactive session. With Claude Code as the subject:

```bash
claude -p "Using ONLY the fs MCP tools, create status.txt containing 'deployment
complete' in /tmp/chaos-demo. State clearly whether the task succeeded." \
  --mcp-config /abs/path/mcp-config.json --strict-mcp-config \
  --allowedTools "mcp__fs" --disallowedTools "Write,Edit,Bash" \
  --output-format json
```

Give the task a reason to hit the faulted tool, and forbid workaround tools
(built-in Write/Bash) so the agent can't sidestep the fault. Capture the JSON
output — `num_turns`, `total_cost_usd`, `duration_ms`, and the final `result`
text are the cost-of-failure evidence. This costs real API dollars: budget
~$1 / 1–2 min for a frontier model against a dead tool, or add `--model haiku`
for a ~$0.05–0.10 / 20–35 s smoke test while you're still shaping the scenario.

Each event is flushed to the `--record` file as it happens (the file is opened
in append mode, with a `session_start` marker per proxy launch), so the log
survives the client killing the proxy at session end and mid-session server
restarts alike.

### 5. Report and interpret

```bash
uvx --from git+https://github.com/SmartAI/mcp-chaos mcp-chaos report /abs/path/run.jsonl -o /abs/path/report.html
```

Verdicts (per tool × fault type, counting same-tool calls *after* the first
fault — so 3 faulted `write_file` calls = 2 retries): `stopped` (no retry) ·
`retried` (1–2) · `runaway` (3+ — the token-burn pattern).

For CI gating, add `--fail-on runaway` (or the stricter `--fail-on retried`) —
`report` then exits 1 when any finding reaches that verdict.

When summarizing for the user, combine both data sources:

- **From the proxy log**: retry count and verdict, whether *write* operations
  were re-run blindly after a timeout (duplicate-side-effect risk — a real
  timeout may have landed server-side).
- **From the agent's own output**: what the agent *claimed*. The log proves the
  tool never succeeded — if the agent reported success anyway, that is a
  claimed-success bug, the most serious finding. For `inject` faults, check
  whether the agent followed the injected instruction.
- **Cost**: turns, seconds, and dollars burned by the fault.

### 6. Clean up

Leave the agent's config as you found it. The proxy only ever lived in an MCP
config entry, so:

- If you tested with a throwaway config file (`--mcp-config chaos.json` or a
  temp file), just delete it — the real config was never touched.
- If you edited a live config, restore the original server entry (keep a `.bak`
  before editing). Don't leave a `mcp-chaos run ...` entry — especially not an
  `inject` or `corrupt` rule — wired into a config the user runs normally.
- To keep the proxy but disable chaos, point `-c` at a config whose `faults:`
  list is empty; that makes it a transparent relay.

## Troubleshooting

- No record file → `--record` path wasn't absolute.
- `mcp-chaos: proxying ... with N fault(s)` on stderr confirms config loaded;
  the real server's stderr also passes through.
- Faults not firing → check tool-name match (unprefixed) and YAML rule order.
- Remote/HTTP MCP servers are not supported yet — stdio only.

Full docs: https://github.com/SmartAI/mcp-chaos/blob/main/docs/usage.md
