"""End-to-end tests: drive the proxy over stdio and assert each fault fires.

The proxy is spawned as a subprocess with the mock server as its target. We speak
JSON-RPC to the proxy's stdin and read its stdout, exactly as a real agent would.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
MOCK = os.path.join(ROOT, "tests", "mock_server.py")


def _proxy(config_yaml: str) -> subprocess.Popen:
    cfg = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    cfg.write(config_yaml)
    cfg.close()
    env = {**os.environ, "PYTHONPATH": SRC}
    return subprocess.Popen(
        [sys.executable, "-m", "mcp_chaos.cli", "run", "-c", cfg.name,
         "--record", cfg.name + ".jsonl"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=env, text=True, bufsize=1,
    )


def _rpc(proc, method, req_id, params=None):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def _call(proc, req_id, tool):
    return _rpc(proc, "tools/call", req_id, {"name": tool, "arguments": {}})


CONFIG = f"""
server:
  command: "{sys.executable} {MOCK}"
faults:
  - tool: "merge_pull_request"
    type: {{TYPE}}
    {{EXTRA}}
"""


def _run_fault(ftype, extra=""):
    proc = _proxy(CONFIG.replace("{TYPE}", ftype).replace("{EXTRA}", extra))
    try:
        assert "result" in _rpc(proc, "initialize", 1)
        resp = _call(proc, 2, "merge_pull_request")
        return resp
    finally:
        proc.stdin.close()
        proc.terminate()


def test_passthrough_untouched_tool():
    proc = _proxy(CONFIG.replace("{TYPE}", "timeout").replace("{EXTRA}", ""))
    try:
        _rpc(proc, "initialize", 1)
        resp = _call(proc, 2, "get_order")  # not the targeted tool
        assert "real data" in resp["result"]["content"][0]["text"]
    finally:
        proc.stdin.close()
        proc.terminate()


def test_timeout():
    resp = _run_fault("timeout")
    assert resp["error"]["code"] == -32001


def test_error():
    resp = _run_fault("error")
    assert "error" in resp


def test_rate_limit():
    resp = _run_fault("rate_limit")
    assert "Rate limit" in resp["error"]["message"]


def test_empty():
    resp = _run_fault("empty")
    assert resp["result"]["content"] == []


def test_slow_still_returns_real():
    start = time.monotonic()
    resp = _run_fault("slow", "delay_ms: 300")
    assert "real data" in resp["result"]["content"][0]["text"]
    assert time.monotonic() - start >= 0.3


def test_corrupt_truncates():
    resp = _run_fault("corrupt")
    text = resp["result"]["content"][0]["text"]
    assert text and "real data" not in text  # truncated before the end


def test_inject_appends_payload():
    resp = _run_fault("inject", 'payload: "PWNED_MARKER"')
    assert "PWNED_MARKER" in resp["result"]["content"][0]["text"]


def test_record_survives_sigterm():
    # Real MCP clients (e.g. Claude Code) SIGTERM the server at session end
    # rather than closing stdin; the run log must not be lost.
    proc = _proxy(CONFIG.replace("{TYPE}", "timeout").replace("{EXTRA}", ""))
    record = proc.args[proc.args.index("--record") + 1]
    try:
        _rpc(proc, "initialize", 1)
        _call(proc, 2, "merge_pull_request")
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    with open(record) as f:
        kinds = [json.loads(line)["kind"] for line in f if line.strip()]
    assert "tool_call" in kinds
    assert "fault" in kinds
