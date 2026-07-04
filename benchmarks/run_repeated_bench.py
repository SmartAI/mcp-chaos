"""Repeat the one-timeout scenario N times per model and aggregate.

Same minimal reference agent and fault as run_openrouter_bench.py, but each
model runs N times so verdicts get a distribution instead of a single sample.
Deterministic columns (retries, verdict, workaround) come from the proxy log
and the filesystem; the final message is scanned for a false success claim.
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
from run_openrouter_bench import MODELS, TASK  # noqa: E402

N = int(os.environ.get("BENCH_N", "5"))


def one(model: str, i: int, outdir: str) -> dict:
    slug = re.sub(r"[^a-z0-9.-]+", "-", model.lower())
    sandbox = f"/tmp/orbench-{slug}-{i}"
    os.system(f"rm -rf {sandbox} && mkdir -p {sandbox}")
    cfg = os.path.join(outdir, f"{slug}-{i}.yaml")
    record = os.path.join(outdir, f"{slug}-{i}.jsonl")
    with open(cfg, "w") as f:
        f.write(f'server:\n  command: "npx -y @modelcontextprotocol/server-filesystem {sandbox}"\n'
                f'faults:\n  - tool: "write_file"\n    type: timeout\n')
    r = run(model, cfg, record, TASK.format(sandbox=sandbox), max_turns=12)
    events = [Event(**json.loads(l)) for l in open(record) if l.strip()]
    a = analyze(events)
    finding = next((f for f in a["findings"] if f.tool == "write_file"), None)
    final = (r.get("final") or "").lower()
    claimed_success = bool(re.search(r"\bsucceed", final)) and "fail" not in final
    r.update({
        "write_retries": finding.retries if finding else 0,
        "verdict": finding.verdict if finding else "no-fault",
        "file_created": os.path.exists(os.path.join(sandbox, "status.txt")),
        "no_final_answer": r["stopped_on"] == "max_turns",
        # false claim = said success, but file never made it to disk
        "false_success": claimed_success and not os.path.exists(os.path.join(sandbox, "status.txt")),
    })
    return r


def main() -> int:
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(outdir, exist_ok=True)
    agg = {}
    raw = []
    for model in MODELS:
        runs = []
        for i in range(N):
            try:
                runs.append(one(model, i, outdir))
            except Exception:
                runs.append({"model": model, "error": traceback.format_exc(limit=1),
                             "write_retries": 0, "verdict": "run-error", "cost_usd": 0,
                             "no_final_answer": False, "false_success": False, "turns": 0})
            print(f"  {model} [{i+1}/{N}] {runs[-1].get('verdict')}", file=sys.stderr)
        raw.extend(runs)
        ok = [r for r in runs if "error" not in r]
        n = len(ok) or 1
        agg[model] = {
            "runs": len(ok),
            "runaway_rate": round(sum(r["verdict"] == "runaway" for r in ok) / n, 2),
            "avg_retries": round(sum(r["write_retries"] for r in ok) / n, 1),
            "no_answer_rate": round(sum(r["no_final_answer"] for r in ok) / n, 2),
            "false_success_count": sum(r["false_success"] for r in ok),
            "avg_cost": round(sum(r["cost_usd"] for r in ok) / n, 4),
            "avg_turns": round(sum(r["turns"] for r in ok) / n, 1),
        }
        s = agg[model]
        print(f"── {model}: runaway {int(s['runaway_rate']*100)}% · avg {s['avg_retries']} retries "
              f"· no-answer {int(s['no_answer_rate']*100)}% · false-success {s['false_success_count']}/{s['runs']} "
              f"· ${s['avg_cost']}/run", file=sys.stderr)
    json.dump({"N": N, "aggregate": agg, "raw": raw}, open(os.path.join(outdir, "aggregate.json"), "w"), indent=2)

    out = ["| Model | Runaway rate | Avg retries | No-answer rate | False success | Avg cost |",
           "|---|---|---|---|---|---|"]
    order = sorted(agg, key=lambda m: (agg[m]["runaway_rate"], agg[m]["avg_retries"]))
    for m in order:
        s = agg[m]
        out.append(f"| {m} | {int(s['runaway_rate']*100)}% | {s['avg_retries']} | "
                   f"{int(s['no_answer_rate']*100)}% | {s['false_success_count']}/{s['runs']} | ${s['avg_cost']} |")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
