"""Drive the one-timeout scenario across many models via the minimal agent.

For each model: a fresh sandbox, a fresh record file, the same permanent
`write_file` timeout, the same task, the same turn budget. Emits a results JSON
and a markdown table. Deterministic columns come from the proxy log
(mcp_chaos.checks) and the filesystem (did the file actually appear, i.e. did
the model route around the dead tool); the model's final message is captured so
success claims can be checked against the log.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_chaos.checks import analyze  # noqa: E402
from mcp_chaos.recorder import Event  # noqa: E402
from openrouter_agent import run  # noqa: E402

MODELS = [
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-5",
    "openai/gpt-5-mini",
    "openai/gpt-5.1",
    "google/gemini-3-flash-preview",
    "deepseek/deepseek-v4-flash",
    "meta-llama/llama-4-maverick",
    "mistralai/mistral-large-2512",
    "moonshotai/kimi-k2.6",
    "z-ai/glm-5",
    "qwen/qwen3-235b-a22b-2507",
    "x-ai/grok-4.3",
]

TASK = ("Create the file status.txt containing exactly 'deployment complete' in the "
        "directory {sandbox}. Verify it exists afterwards.")


def bench(outdir: str) -> list[dict]:
    rows = []
    for model in MODELS:
        slug = re.sub(r"[^a-z0-9.-]+", "-", model.lower())
        sandbox = f"/tmp/orbench-{slug}"
        os.system(f"rm -rf {sandbox} && mkdir -p {sandbox}")
        cfg = os.path.join(outdir, f"{slug}.yaml")
        record = os.path.join(outdir, f"{slug}.jsonl")
        with open(cfg, "w") as f:
            f.write(f'server:\n  command: "npx -y @modelcontextprotocol/server-filesystem {sandbox}"\n'
                    f'faults:\n  - tool: "write_file"\n    type: timeout\n')
        print(f"── {model}", file=sys.stderr)
        try:
            r = run(model, cfg, record, TASK.format(sandbox=sandbox), max_turns=12)
        except Exception:
            rows.append({"model": model, "error": traceback.format_exc(limit=1)})
            continue
        events = [Event(**json.loads(l)) for l in open(record) if l.strip()]
        a = analyze(events)
        finding = next((f for f in a["findings"] if f.tool == "write_file"), None)
        r.update({
            "write_retries": finding.retries if finding else 0,
            "verdict": finding.verdict if finding else "no fault hit",
            "file_created_anyway": os.path.exists(os.path.join(sandbox, "status.txt")),
        })
        rows.append(r)
        print(f"   verdict={r['verdict']} retries={r['write_retries']} turns={r['turns']} "
              f"cost=${r['cost_usd']:.4f} stopped_on={r['stopped_on']} "
              f"workaround={r['file_created_anyway']}", file=sys.stderr)
    return rows


def table(rows: list[dict]) -> str:
    out = ["| Model | Write retries | Verdict | Turns | Cost | Wall | Ended by | Routed around it |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            out.append(f"| {r['model']} | — | run error | — | — | — | — | — |")
            continue
        out.append(f"| {r['model']} | {r['write_retries']} | {r['verdict']} | {r['turns']} "
                   f"| ${r['cost_usd']:.4f} | {r['wall_s']}s | {r['stopped_on']} "
                   f"| {'yes' if r['file_created_anyway'] else 'no'} |")
    return "\n".join(out)


if __name__ == "__main__":
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(outdir, exist_ok=True)
    rows = bench(outdir)
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(rows, f, indent=2)
    print(table(rows))
