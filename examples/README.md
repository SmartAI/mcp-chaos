# Example fault configs

Ready-to-run `faults.yaml` presets for mcp-chaos. Each file has a header comment
explaining the failure mode it hunts and what to look for in the report.

| File | Scenario |
|---|---|
| [`faults.yaml`](faults.yaml) | Minimal starter config (timeout + inject). |
| [`dead-write-tool.yaml`](dead-write-tool.yaml) | A write/merge tool that times out forever — the classic retry-storm / blind-re-run test. |
| [`flaky-tool.yaml`](flaky-tool.yaml) | A degraded dependency: 30% errors plus added latency. |
| [`prompt-injection.yaml`](prompt-injection.yaml) | Adversarial text injected into read/search results (indirect prompt injection). Test resources only. |

## How to run

Point the proxy at any of these in your agent's MCP config (use absolute paths):

```
"command": "uvx",
"args": ["--from", "git+https://github.com/SmartAI/mcp-chaos", "mcp-chaos",
         "run", "-c", "/abs/path/examples/dead-write-tool.yaml",
         "--record", "/abs/path/run.jsonl"]
```

Then use your agent normally and render the report:

```bash
uvx --from git+https://github.com/SmartAI/mcp-chaos mcp-chaos report /abs/path/run.jsonl -o report.html
```

See [`docs/usage.md`](../docs/usage.md) for the full setup guide, the fault-rule
reference, and how to read the verdicts.
