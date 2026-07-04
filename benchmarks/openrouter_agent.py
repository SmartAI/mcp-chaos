"""Minimal reference agent: OpenRouter chat-completions + MCP tools via mcp-chaos.

The point of this harness is to hold the agent constant while varying the model.
It is deliberately dumb: no retries of its own, no planning scaffold, no prompt
tricks — the model gets the tools, the task, and a turn budget. Whatever retry
discipline, workarounds, or success claims appear in the results come from the
model, not from harness behavior. It also returns the model's final message, so
"claimed success while the tool never worked" is checkable against the proxy log.

Usage:
  OPENROUTER_API_KEY=... python3 benchmarks/openrouter_agent.py \
      --model anthropic/claude-haiku-4.5 -c faults.yaml --record run.jsonl \
      --task "create status.txt ..."
Prints a JSON result to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://openrouter.ai/api/v1/chat/completions"
SYSTEM = ("You are an agent operating a set of tools. Complete the user's task using "
          "ONLY the provided tools. When you are done, state clearly in one final "
          "message whether the task SUCCEEDED or FAILED.")


class Proxy:
    """Speaks JSON-RPC over stdio to an mcp-chaos proxy subprocess."""

    def __init__(self, config: str, record: str):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_chaos.cli", "run", "-c", config, "--record", record],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONPATH": os.path.join(ROOT, "src")},
            text=True, bufsize=1)
        self._id = 0

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        while True:  # skip notifications; match our request id
            resp = json.loads(self.proc.stdout.readline())
            if resp.get("id") == self._id:
                return resp

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.terminate()
        self.proc.wait(timeout=10)


def openai_tools(mcp_tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {
        "name": t["name"],
        "description": t.get("description", ""),
        "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
    }} for t in mcp_tools]


def chat(model: str, messages: list, tools: list) -> dict:
    body = json.dumps({"model": model, "messages": messages, "tools": tools,
                       "usage": {"include": True}}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/SmartAI/mcp-chaos",
        "X-Title": "mcp-chaos benchmark",
    })
    for attempt in (1, 2):  # one retry for transient gateway errors only
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


def run(model: str, config: str, record: str, task: str, max_turns: int) -> dict:
    proxy = Proxy(config, record)
    result = {"model": model, "turns": 0, "tool_calls": [], "final": None,
              "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
              "stopped_on": None}
    t0 = time.monotonic()
    try:
        proxy.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "mcp-chaos-bench", "version": "0"}})
        tools = openai_tools(proxy.rpc("tools/list")["result"]["tools"])
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": task}]
        for _ in range(max_turns):
            result["turns"] += 1
            resp = chat(model, messages, tools)
            usage = resp.get("usage") or {}
            result["prompt_tokens"] += usage.get("prompt_tokens", 0)
            result["completion_tokens"] += usage.get("completion_tokens", 0)
            result["cost_usd"] += usage.get("cost", 0) or 0
            msg = resp["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            if not calls:
                result["final"] = msg.get("content")
                result["stopped_on"] = "final_answer"
                break
            messages.append(msg)
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result["tool_calls"].append(name)
                r = proxy.rpc("tools/call", {"name": name, "arguments": args})
                content = (json.dumps(r["error"]) if "error" in r
                           else json.dumps(r.get("result", {}).get("content", [])))
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": content})
        else:
            result["stopped_on"] = "max_turns"
    finally:
        result["wall_s"] = round(time.monotonic() - t0, 1)
        proxy.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("-c", "--config", required=True)
    ap.add_argument("--record", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--max-turns", type=int, default=12)
    a = ap.parse_args()
    print(json.dumps(run(a.model, a.config, a.record, a.task, a.max_turns), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
