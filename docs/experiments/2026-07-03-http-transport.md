# Experiment: fault-inject a hosted MCP server over Streamable HTTP

**Date:** 2026-07-03 · **Server:** Context7's hosted endpoint
(`https://mcp.context7.com/mcp`, keyless tier), a production MCP service we
don't run.

## Setup

The whole change from a stdio setup is `server.url` instead of
`server.command` ([config](2026-07-03-http-transport.faults.yaml)):

```yaml
server:
  url: "https://mcp.context7.com/mcp"
faults:
  - tool: "query-docs"
    type: error
```

Driven by a real stdio MCP session (a JSON-RPC client on the proxy's stdin —
the same seat any MCP client sits in). Session output, byte-identical to
[`2026-07-03-http-transport.out.txt`](2026-07-03-http-transport.out.txt):

```
server: {"name": "Context7", "version": "3.2.2", "websiteUrl": "https://context7.com", "description": "Context7 provides up-to-d ...
tools: ['resolve-library-id', 'query-docs']
resolve-library-id (live, un-faulted): Available Libraries: ...
query-docs (fault injected): {"code": -32603, "message": "Internal error: service unavailable"}
```

The un-faulted `resolve-library-id` call went to the live backend and came
back with real results in 1.1 s; the `query-docs` call never left the proxy —
the fault short-circuited it. From the recorded run log
([`2026-07-03-http-transport.run.jsonl`](2026-07-03-http-transport.run.jsonl)):

```
{"t": 2.318, "kind": "tool_call", "tool": "query-docs", "detail": {"id": 4, "args_chars": 67, "args_hash": "445f9187"}}
{"t": 2.318, "kind": "fault", "tool": "query-docs", "detail": {"type": "error", "id": 4, "mode": "short_circuit"}}
```

## Takeaway

Same one-line config change, same seven fault types, same event log — but the
upstream is a hosted server you don't operate and could never make fail on
demand. Cost: $0 (keyless tier, two requests).

## Field note

Context7 v3 renamed `get-library-docs` to `query-docs` and made `query` a
required argument of `resolve-library-id`; the first session captured the
server's real validation error. Fault rules match by tool name, so the fault
fired regardless — but the committed run targets a tool the server actually
advertises.
