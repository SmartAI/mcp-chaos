"""Tests for record & replay: hermetic tool mocks from a recorded cassette.

Unit tests drive the Cassette lookup logic directly; the e2e test records a
real proxied session to a cassette, then replays it with no server behind it
and asserts the agent sees identical responses.
"""

import json
import os
import subprocess
import sys
import tempfile

from mcp_chaos.cassette import Cassette, CassetteWriter, call_key

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
MOCK = os.path.join(ROOT, "tests", "mock_server.py")


def _cassette(tmp_path, entries):
    path = tmp_path / "cassette.jsonl"
    w = CassetteWriter(str(path))
    for method, tool, key, response in entries:
        w.log(method, tool, key, response)
    return Cassette.load(str(path))


RESULT_A = {"result": {"content": [{"type": "text", "text": "A"}]}}
RESULT_B = {"result": {"content": [{"type": "text", "text": "B"}]}}


def test_tool_call_round_trip(tmp_path):
    key = call_key("tools/call", {"name": "get_order", "arguments": {"id": 7}})
    c = _cassette(tmp_path, [("tools/call", "get_order", key, RESULT_A)])
    resp = c.reply({"jsonrpc": "2.0", "id": 42, "method": "tools/call",
                    "params": {"name": "get_order", "arguments": {"id": 7}}})
    assert resp["id"] == 42
    assert resp["result"]["content"][0]["text"] == "A"


def test_fifo_then_sticky_last(tmp_path):
    key = call_key("tools/call", {"name": "get_order", "arguments": {}})
    c = _cassette(tmp_path, [("tools/call", "get_order", key, RESULT_A),
                             ("tools/call", "get_order", key, RESULT_B)])
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "get_order", "arguments": {}}}
    texts = [c.reply(msg)["result"]["content"][0]["text"] for _ in range(3)]
    assert texts == ["A", "B", "B"]  # FIFO, then the last response repeats


def test_unrecorded_tool_call_gets_honest_error(tmp_path):
    key = call_key("tools/call", {"name": "get_order", "arguments": {}})
    c = _cassette(tmp_path, [("tools/call", "get_order", key, RESULT_A)])
    resp = c.reply({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "get_order", "arguments": {"other": 1}}})
    assert "error" in resp
    assert "get_order" in resp["error"]["message"]


def test_initialize_matches_by_method_despite_different_params(tmp_path):
    # client info varies between the recording client and the replaying one
    key = call_key("initialize", {"clientInfo": {"name": "recorder"}})
    c = _cassette(tmp_path, [("initialize", None, key,
                              {"result": {"protocolVersion": "2025-06-18"}})])
    resp = c.reply({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"clientInfo": {"name": "someone-else"}}})
    assert resp["result"]["protocolVersion"] == "2025-06-18"


def test_notifications_get_no_reply(tmp_path):
    c = _cassette(tmp_path, [])
    assert c.reply({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping_answered_even_when_not_recorded(tmp_path):
    c = _cassette(tmp_path, [])
    resp = c.reply({"jsonrpc": "2.0", "id": 9, "method": "ping"})
    assert resp == {"jsonrpc": "2.0", "id": 9, "result": {}}


def test_recorded_error_replays_as_error(tmp_path):
    key = call_key("tools/call", {"name": "merge", "arguments": {}})
    c = _cassette(tmp_path, [("tools/call", "merge", key,
                              {"error": {"code": -32001, "message": "Request timed out"}})])
    resp = c.reply({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "merge", "arguments": {}}})
    assert resp["error"]["code"] == -32001


# --- end to end: record through the proxy, replay with no server behind it ---


def _rpc(proc, method, req_id, params=None):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def _spawn(*args):
    env = {**os.environ, "PYTHONPATH": SRC}
    return subprocess.Popen(
        [sys.executable, "-m", "mcp_chaos.cli", *args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=env, text=True, bufsize=1,
    )


def test_e2e_record_then_hermetic_replay(tmp_path):
    cassette = str(tmp_path / "cassette.jsonl")
    cfg = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    cfg.write(f'server:\n  command: "{sys.executable} {MOCK}"\n'
              'faults:\n  - tool: "merge_pull_request"\n    type: timeout\n')
    cfg.close()

    rec = _spawn("run", "-c", cfg.name, "--record", str(tmp_path / "run.jsonl"),
                 "--cassette", cassette)
    try:
        init = _rpc(rec, "initialize", 1)
        listing = _rpc(rec, "tools/list", 2)
        real = _rpc(rec, "tools/call", 3, {"name": "get_order", "arguments": {"id": 7}})
        faulted = _rpc(rec, "tools/call", 4,
                       {"name": "merge_pull_request", "arguments": {}})
    finally:
        rec.stdin.close()
        rec.terminate()
        rec.wait(timeout=5)

    # replay serves the same session with no real server and no fault config
    rep = _spawn("replay", cassette)
    try:
        assert _rpc(rep, "initialize", 1)["result"] == init["result"]
        assert _rpc(rep, "tools/list", 2)["result"] == listing["result"]
        again = _rpc(rep, "tools/call", 3, {"name": "get_order", "arguments": {"id": 7}})
        assert again["result"] == real["result"]
        # the injected fault was recorded as the agent saw it
        f = _rpc(rep, "tools/call", 4, {"name": "merge_pull_request", "arguments": {}})
        assert f["error"]["code"] == faulted["error"]["code"] == -32001
        # a call that never happened in the recording fails honestly
        miss = _rpc(rep, "tools/call", 5, {"name": "get_order", "arguments": {"id": 999}})
        assert "error" in miss
    finally:
        rep.stdin.close()
        rep.terminate()
        rep.wait(timeout=5)
