# Experiment: config doctor on a realistic five-server config

**Date:** 2026-07-03 · **Command:** one line, no agent, exit code 1.

## Setup

A five-entry `mcpServers` config ([`2026-07-03-config-doctor.mcp.json`](2026-07-03-config-doctor.mcp.json))
of the kind that accretes in a real client over a few weeks:

- `filesystem` — official `@modelcontextprotocol/server-filesystem` (real, healthy)
- `repo-fs` — a *second* filesystem server pointed at another directory (real,
  healthy — and a trap: same 14 tool names)
- `context7` — `@upstash/context7-mcp` (real, healthy)
- `github` — a binary that isn't installed on this machine (the broken entry)
- `sentry` — a hosted Streamable HTTP entry (doctor reports these but checks
  stdio only today)

Run on macOS (Darwin 25.5.0), `npx` caches warm — this is the second
invocation; the first run's numbers differed only in startup latency
(~800 ms vs ~550 ms per server).

## Command and full output

```bash
uvx mcp-chaos doctor 2026-07-03-config-doctor.mcp.json
```

Output, byte-identical to [`2026-07-03-config-doctor.out.txt`](2026-07-03-config-doctor.out.txt):

```
✔ filesystem: 14 tools · ~3214 tokens of definitions · ready in 546 ms
✔ repo-fs: 14 tools · ~3214 tokens of definitions · ready in 536 ms
✔ context7: 2 tools · ~1171 tokens of definitions · ready in 638 ms
✘ github: launch failed: [Errno 2] No such file or directory: 'github-mcp-server-not-installed'
- sentry: skipped — HTTP transport not checked yet (https://mcp.sentry.dev/mcp)
⚠ tool name collision: create_directory (filesystem, repo-fs)
⚠ tool name collision: directory_tree (filesystem, repo-fs)
⚠ tool name collision: edit_file (filesystem, repo-fs)
⚠ tool name collision: get_file_info (filesystem, repo-fs)
⚠ tool name collision: list_allowed_directories (filesystem, repo-fs)
⚠ tool name collision: list_directory (filesystem, repo-fs)
⚠ tool name collision: list_directory_with_sizes (filesystem, repo-fs)
⚠ tool name collision: move_file (filesystem, repo-fs)
⚠ tool name collision: read_file (filesystem, repo-fs)
⚠ tool name collision: read_media_file (filesystem, repo-fs)
⚠ tool name collision: read_multiple_files (filesystem, repo-fs)
⚠ tool name collision: read_text_file (filesystem, repo-fs)
⚠ tool name collision: search_files (filesystem, repo-fs)
⚠ tool name collision: write_file (filesystem, repo-fs)
5 server(s) · 30 tools · ~7599 tokens of tool definitions per session
1 problem(s) found
```

Exit code: **1** (a server is broken), so this drops straight into CI.

## What each line buys you

- The **✘ github** line catches a dead server in ~1 second, before any agent
  burns a session discovering it (compare the [timeout
  experiment](2026-07-03-claude-code-timeout.md): one dead tool cost a real
  agent ~$1 per run to discover the hard way).
- The **14 ⚠ collision** lines are the silent failure mode of stacking two
  same-family servers: which `write_file` the client routes to is
  client-defined, and no agent transcript will ever tell you.
- The **summary line** prices the config: ~7.6k context tokens of tool
  definitions paid on *every session* before the agent reads a single word of
  your task.
