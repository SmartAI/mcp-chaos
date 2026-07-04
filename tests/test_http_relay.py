"""End-to-end tests for the Streamable HTTP relay.

The agent still speaks stdio to mcp-chaos; `server.url` makes the proxy relay
upstream over Streamable HTTP with the same fault engine and recording. The
relay is spawned as a subprocess against the in-process mock HTTP server.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

import pytest

import mock_http_server

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")


@pytest.fixture()
def http_server():
    server, url = mock_http_server.start()
    yield server, url
    server.shutdown()


def _relay(url, faults="faults: []\n", extra=""):
    cfg = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    cfg.write(f'server:\n  url: "{url}"\n{extra}{faults}')
    cfg.close()
    env = {**os.environ, "PYTHONPATH": SRC}
    return subprocess.Popen(
        [sys.executable, "-m", "mcp_chaos.cli", "run", "-c", cfg.name,
         "--record", cfg.name + ".jsonl"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=env, text=True, bufsize=1,
    )


def _send(proc, method, req_id=None, params=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        msg["id"] = req_id
    if params is not None:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def _read(proc):
    return json.loads(proc.stdout.readline())


def _rpc(proc, method, req_id, params=None):
    _send(proc, method, req_id, params)
    return _read(proc)


def _shutdown(proc):
    proc.stdin.close()
    proc.terminate()
    proc.wait(timeout=5)


def test_passthrough_over_http(http_server):
    server, url = http_server
    proc = _relay(url)
    try:
        init = _rpc(proc, "initialize", 1, {"clientInfo": {"name": "t"}})
        assert init["result"]["serverInfo"]["name"] == "mock-http"
        listing = _rpc(proc, "tools/list", 2)
        assert len(listing["result"]["tools"]) == 2
        resp = _rpc(proc, "tools/call", 3,
                    {"name": "merge_pull_request", "arguments": {}})
        assert "real data" in resp["result"]["content"][0]["text"]
    finally:
        _shutdown(proc)


def test_sse_response_forwards_notification_then_result(http_server):
    server, url = http_server
    proc = _relay(url)
    try:
        _rpc(proc, "initialize", 1)
        first = _rpc(proc, "tools/call", 2, {"name": "get_order", "arguments": {}})
        assert first["method"] == "notifications/progress"  # streamed ahead
        result = _read(proc)
        assert "real data" in result["result"]["content"][0]["text"]
    finally:
        _shutdown(proc)


def test_session_id_propagated_after_initialize(http_server):
    server, url = http_server
    proc = _relay(url)
    try:
        _rpc(proc, "initialize", 1)
        _rpc(proc, "tools/list", 2)
    finally:
        _shutdown(proc)
    listed = [j for j in server.journal if j["method"] == "tools/list"]
    assert listed and listed[0]["session"] == mock_http_server.SESSION_ID


def test_fault_short_circuits_before_the_network(http_server):
    server, url = http_server
    faults = 'faults:\n  - tool: "merge_pull_request"\n    type: timeout\n'
    proc = _relay(url, faults)
    try:
        _rpc(proc, "initialize", 1)
        resp = _rpc(proc, "tools/call", 2,
                    {"name": "merge_pull_request", "arguments": {}})
        assert resp["error"]["code"] == -32001
    finally:
        _shutdown(proc)
    # the faulted call never crossed the wire
    assert not [j for j in server.journal if j["tool"] == "merge_pull_request"]


def test_inject_mutates_the_http_response(http_server):
    server, url = http_server
    faults = ('faults:\n  - tool: "merge_pull_request"\n    type: inject\n'
              '    payload: "PWNED_MARKER"\n')
    proc = _relay(url, faults)
    try:
        _rpc(proc, "initialize", 1)
        resp = _rpc(proc, "tools/call", 2,
                    {"name": "merge_pull_request", "arguments": {}})
        assert "PWNED_MARKER" in resp["result"]["content"][0]["text"]
    finally:
        _shutdown(proc)


def test_run_log_records_http_traffic(http_server):
    server, url = http_server
    proc = _relay(url)
    record = proc.args[proc.args.index("--record") + 1]
    try:
        _rpc(proc, "initialize", 1)
        _rpc(proc, "tools/list", 2)
        _rpc(proc, "tools/call", 3, {"name": "merge_pull_request", "arguments": {}})
    finally:
        _shutdown(proc)
    with open(record) as f:
        events = [json.loads(line) for line in f if line.strip()]
    by_kind = {e["kind"]: e for e in events}
    assert by_kind["tools_list"]["detail"]["tools"] == ["get_order", "merge_pull_request"]
    assert by_kind["tool_call"]["tool"] == "merge_pull_request"
    assert by_kind["tool_result"]["detail"]["ok"] is True
    assert by_kind["tool_result"]["detail"]["ms"] >= 0


def test_upstream_down_returns_jsonrpc_error():
    proc = _relay("http://127.0.0.1:9")  # nothing listens on port 9
    try:
        _send(proc, "initialize", 1)
        deadline = time.monotonic() + 10
        resp = _read(proc)
        assert time.monotonic() < deadline
        assert resp["error"]["code"] == -32000
        assert resp["id"] == 1
    finally:
        _shutdown(proc)


def test_config_rejects_url_and_command_together(tmp_path):
    from mcp_chaos import config
    p = tmp_path / "f.yaml"
    p.write_text('server:\n  command: "x"\n  url: "http://y"\nfaults: []\n')
    with pytest.raises(ValueError):
        config.load(str(p))


def test_config_requires_url_or_command(tmp_path):
    from mcp_chaos import config
    p = tmp_path / "f.yaml"
    p.write_text("server: {}\nfaults: []\n")
    with pytest.raises(ValueError):
        config.load(str(p))
