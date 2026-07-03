"""Unit tests for the deterministic MCP-efficiency profile."""

from mcp_chaos.efficiency import profile
from mcp_chaos.recorder import Event


def ev(t, kind, tool=None, **detail):
    return Event(t=t, kind=kind, tool=tool, detail=detail)


def test_context_tax_and_unused_tools():
    events = [
        ev(0.0, "session_start"),
        ev(0.1, "tools_list", count=3, chars=4000,
           tools=["get_order", "merge_pull_request", "close_issue"]),
        ev(0.2, "tool_call", "get_order", id=1, args_hash="aa", args_chars=10),
    ]
    p = profile(events)
    assert p["has_data"]
    assert p["advertised"] == 3
    assert p["listing_tokens"] == 1000  # chars // 4
    assert p["unused"] == ["close_issue", "merge_pull_request"]


def test_per_tool_stats():
    events = [
        ev(0.1, "tool_call", "get_order", id=1, args_hash="aa", args_chars=10),
        ev(0.2, "tool_result", "get_order", id=1, ok=True, ms=100, chars=800),
        ev(0.3, "tool_call", "get_order", id=2, args_hash="aa", args_chars=10),
        ev(0.4, "tool_result", "get_order", id=2, ok=False, ms=300, chars=80, code=-32603),
    ]
    t = profile(events)["tools"]["get_order"]
    assert t["calls"] == 2
    assert t["errors"] == 1
    assert t["avg_ms"] == 200
    assert t["result_tokens"] == 220  # (800 + 80) // 4


def test_corrected_retry_after_error_counts_as_friction():
    events = [
        ev(0.1, "tool_call", "search", id=1, args_hash="aa", args_chars=20),
        ev(0.2, "tool_result", "search", id=1, ok=False, ms=50, chars=60, code=-32602),
        ev(0.3, "tool_call", "search", id=2, args_hash="bb", args_chars=25),
        ev(0.4, "tool_result", "search", id=2, ok=True, ms=60, chars=500),
    ]
    assert profile(events)["tools"]["search"]["corrected_retries"] == 1


def test_identical_retry_after_error_is_not_corrected():
    events = [
        ev(0.1, "tool_call", "search", id=1, args_hash="aa", args_chars=20),
        ev(0.2, "tool_result", "search", id=1, ok=False, ms=50, chars=60),
        ev(0.3, "tool_call", "search", id=2, args_hash="aa", args_chars=20),
    ]
    assert profile(events)["tools"]["search"]["corrected_retries"] == 0


def test_injected_faults_do_not_pollute_error_stats():
    # Short-circuited faults produce `fault` events, not `tool_result` errors.
    events = [
        ev(0.1, "tool_call", "write_file", id=1, args_hash="aa", args_chars=30),
        ev(0.1, "fault", "write_file", type="timeout", id=1, mode="short_circuit"),
    ]
    t = profile(events)["tools"]["write_file"]
    assert t["calls"] == 1
    assert t["errors"] == 0


def test_report_renders_efficiency_section():
    from mcp_chaos.report import render

    html = render([
        ev(0.1, "tools_list", count=2, chars=800, tools=["get_order", "close_issue"]),
        ev(0.2, "tool_call", "get_order", id=1, args_hash="aa", args_chars=10),
        ev(0.3, "tool_result", "get_order", id=1, ok=True, ms=120, chars=400),
    ])
    assert "MCP efficiency" in html
    assert "close_issue" in html  # unused tool called out
    assert "200 tokens" in html   # context tax: 800 chars // 4


def test_report_notes_missing_efficiency_data_on_old_logs():
    from mcp_chaos.report import render

    html = render([ev(0.1, "tool_call", "write_file", id=1)])
    assert "MCP efficiency" in html
    assert "no efficiency data" in html


def test_old_logs_without_capture_events_have_no_data():
    events = [
        ev(0.0, "session_start"),
        ev(0.1, "tool_call", "write_file", id=1),
        ev(0.1, "fault", "write_file", type="timeout", id=1),
    ]
    p = profile(events)
    assert not p["has_data"]
    assert p["advertised"] is None
