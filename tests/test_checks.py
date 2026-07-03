"""Unit tests for the deterministic resilience analyzer."""

from mcp_chaos.checks import RUNAWAY_THRESHOLD, analyze
from mcp_chaos.recorder import Event


def _call(tool):
    return Event(t=0.0, kind="tool_call", tool=tool)


def _fault(tool, ftype="timeout"):
    return Event(t=0.0, kind="fault", tool=tool, detail={"type": ftype})


def test_stopped_when_no_retry():
    events = [_call("merge"), _fault("merge")]
    result = analyze(events)
    assert result["findings"][0].verdict == "stopped"
    assert result["runaways"] == 0


def test_retried_once():
    events = [_call("merge"), _fault("merge"), _call("merge")]
    assert analyze(events)["findings"][0].verdict == "retried"


def test_runaway_loop():
    events = [_call("merge"), _fault("merge")] + [_call("merge")] * RUNAWAY_THRESHOLD
    result = analyze(events)
    assert result["findings"][0].verdict == "runaway"
    assert result["runaways"] == 1


def test_counts_only_same_tool():
    events = [_call("merge"), _fault("merge"), _call("other"), _call("merge")]
    # one retry of "merge", the "other" call is ignored
    assert analyze(events)["findings"][0].retries == 1


def test_one_finding_per_tool_and_fault_type():
    # A permanently failing tool fires a fault on every retry; that is one
    # story ("retried N times"), not N overlapping findings.
    events = [_call("merge"), _fault("merge"),
              _call("merge"), _fault("merge"),
              _call("merge"), _fault("merge")]
    result = analyze(events)
    assert len(result["findings"]) == 1
    assert result["findings"][0].retries == 2
    assert result["findings"][0].verdict == "retried"


def test_totals():
    events = [_call("a"), _call("a"), _fault("a")]
    result = analyze(events)
    assert result["tool_calls"] == 2
    assert result["faults"] == 1
