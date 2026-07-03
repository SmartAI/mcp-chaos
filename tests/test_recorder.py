"""Unit tests for the JSONL run recorder.

Some MCP clients (observed with Codex CLI) restart the MCP server mid-session,
relaunching the proxy. The record file must survive that: append, never truncate.
"""

import json

from mcp_chaos.checks import analyze
from mcp_chaos.recorder import Event, Recorder
from mcp_chaos.report import render


def _read(path):
    with open(path) as f:
        return [Event(**json.loads(line)) for line in f if line.strip()]


def test_restart_appends_instead_of_truncating(tmp_path):
    path = str(tmp_path / "run.jsonl")
    first = Recorder(path)
    first.log("tool_call", tool="write_file", id=1)
    first.log("fault", tool="write_file", type="timeout", id=1)

    second = Recorder(path)  # client restarted the proxy mid-session
    second.log("tool_call", tool="write_file", id=2)

    kinds = [e.kind for e in _read(path)]
    assert kinds.count("session_start") == 2
    assert kinds.count("tool_call") == 2  # first session's events survived
    assert kinds.count("fault") == 1


def test_session_start_marker_shape(tmp_path):
    path = str(tmp_path / "run.jsonl")
    Recorder(path, command="mock-server", faults=1)
    (event,) = _read(path)
    assert event.kind == "session_start"
    assert event.t == 0.0
    assert "started_at" in event.detail
    assert event.detail["command"] == "mock-server"
    assert event.detail["faults"] == 1


def test_analyze_and_report_ignore_session_markers(tmp_path):
    path = str(tmp_path / "run.jsonl")
    first = Recorder(path)
    first.log("tool_call", tool="merge", id=1)
    first.log("fault", tool="merge", type="timeout", id=1)
    second = Recorder(path)
    second.log("tool_call", tool="merge", id=1)

    events = _read(path)
    result = analyze(events)
    assert result["tool_calls"] == 2
    assert result["faults"] == 1
    assert result["findings"][0].verdict == "retried"
    assert "session_start" in render(events)  # timeline renders it, no crash
