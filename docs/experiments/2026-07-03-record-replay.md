# Experiment: record a real session, replay it with no server behind it

**Date:** 2026-07-03 · **Agent:** headless Claude Code (`claude -p`, model
haiku) · **Real server:** `@modelcontextprotocol/server-filesystem` v0.2.0.

## Run 1 — record

The proxy fronts the real filesystem server with **zero faults** and
`--cassette` on ([config](2026-07-03-record-replay.faults.yaml)). Task: list
the allowed directory, create `notes.txt` containing `cassette demo`, read it
back. The agent completed it normally; the proxy captured every response the
agent saw into [`2026-07-03-record-replay.cassette.jsonl`](2026-07-03-record-replay.cassette.jsonl)
— 5 entries: `initialize`, `tools/list`, and three `tools/call`s. Two of them:

```
{"method": "tools/call", "tool": "list_allowed_directories", "key": "99914b93", "response": {"result": {"content": [{"type": "text", "text": "Allowed directories:\n/private/tmp/chaos-replay"}], "structuredContent": {"content": "Allowed directories:\n/private/tmp/chaos-replay"}}}}
{"method": "tools/call", "tool": "write_file", "key": "e3c91c3e", "response": {"result": {"content": [{"type": "text", "text": "Successfully wrote to /private/tmp/chaos-replay/notes.txt"}], "structuredContent": {"content": "Successfully wrote to /private/tmp/chaos-replay/notes.txt"}}}}
```

Final answer ([full text](2026-07-03-record-replay.record.out.txt)): created
and read back `cassette demo`. The file really existed on disk after this run.

## Run 2 — replay, with the world deleted

Then we **deleted the sandbox directory entirely** (`rm -rf
/tmp/chaos-replay`) and swapped the MCP config to serve the cassette instead
of launching any server:

```json
{"mcpServers": {"fs": {"command": "uvx",
  "args": ["mcp-chaos", "replay", "/abs/2026-07-03-record-replay.cassette.jsonl"]}}}
```

Same task, same headless agent. Its answer, byte-identical to
[`2026-07-03-record-replay.replay.out.txt`](2026-07-03-record-replay.replay.out.txt):

```
Done. 

**Results:**
1. **Allowed directory:** `/private/tmp/chaos-replay`
2. **File created:** `/private/tmp/chaos-replay/notes.txt`
3. **File contents:** `cassette demo`
```

Meanwhile, on the actual machine:

```
$ ls /tmp/chaos-replay
"/tmp/chaos-replay": No such file or directory (os error 2)
```

No filesystem server ran, no file was written, no directory existed — every
tool response came from the recording, matched by (tool, argument hash).
Cost: two haiku runs (~$0.03 each); the replay run's *tool side* is $0 and
fully deterministic, which is the point: record one good session against the
real backend, then CI replays it forever — free, offline, and immune to flaky
or paid upstreams.

## Field note

The first record attempt failed usefully: filesystem-server v0.2.0 prefers
the client's MCP *roots* over its command-line directory, so Claude Code
silently re-scoped it to the workspace. Running `claude -p` from inside the
sandbox aligned the root. Cassette replay sidesteps the whole class — replay
ignores roots and answers exactly what was recorded.
