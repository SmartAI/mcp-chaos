# mcp-chaos

**Chaos engineering for AI agents, at the protocol layer.**

Your agent works in demos. Production is different: tools time out, APIs rate-limit, results come back malformed or poisoned. Most agent incidents come from tool-call failures — not model quality. `mcp-chaos` is a transparent MCP proxy that sits between any agent and its tools, injects failures you configure, and reports how the agent actually behaves: does it retry sanely, loop forever, or **lie to you that the task succeeded**?

No code changes. No SDK. Point your MCP config at the proxy and break things on purpose — before production does.

```
Agent (Claude Code / OpenClaw / Cursor / yours)
        │  MCP
        ▼
   ┌───────────┐    faults.yaml: timeout, 429, garbage JSON,
   │ mcp-chaos │◄── empty results, slow drip, injected text
   └───────────┘
        │  MCP
        ▼
   Real MCP servers (GitHub, filesystem, DB, ...)
```

## Why protocol layer?

Existing tools test agents *you write* (Python SDKs, eval frameworks). `mcp-chaos` tests any agent *you run* — because it speaks MCP, it works with every MCP client, in any language, with zero integration code.

## Fault types (MVP)

| Fault | What it simulates |
|---|---|
| `timeout` | Tool hangs / network death |
| `error` | 5xx / service unavailable |
| `rate_limit` | 429 with retry-after |
| `slow` | Degraded latency |
| `empty` | 200 OK with no data |
| `corrupt` | Malformed / truncated JSON |
| `inject` | Adversarial text in tool results (indirect prompt injection) |

## What it checks

- Retry behavior: sane backoff vs. infinite loops (token burn)
- Honesty: did the agent claim success while the tool actually failed?
- Side-effect safety: does it blindly re-run write operations?

## Status

Pre-alpha. Under active development — star/watch to follow.

## Quickstart

```bash
# 1. Describe the faults to inject (see examples/faults.yaml)
# 2. Point your agent's MCP config at the proxy instead of the real server:
uvx mcp-chaos run -c faults.yaml --record run.jsonl
# 3. After the session, render the timeline:
uvx mcp-chaos report run.jsonl -o report.html
```

## License

MIT
