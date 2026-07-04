"""Unit tests for duplicate-write detection.

The question: did a retry double-execute a write? Two deterministic verdicts,
both computed purely from proxy traffic:

- double_executed: the same write-like tool ran to an ok result >= 2 times with
  identical arguments — the write really happened twice at the real server.
- replayed_after_fault: an identical write was re-sent after a fault on that
  tool. Harmless under our short-circuit faults (the server never executed the
  first), but this is exactly the behavior that double-executes against a real
  flaky server.
"""

from mcp_chaos.checks import analyze, is_write_like
from mcp_chaos.recorder import Event


def _call(tool, id, args_hash="aaaa1111"):
    return Event(t=0.0, kind="tool_call", tool=tool,
                 detail={"id": id, "args_hash": args_hash})


def _fault(tool, id, ftype="timeout"):
    return Event(t=0.0, kind="fault", tool=tool, detail={"type": ftype, "id": id})


def _result(tool, id, ok=True):
    return Event(t=0.0, kind="tool_result", tool=tool, detail={"id": id, "ok": ok})


def test_double_executed_when_identical_write_succeeds_twice():
    # slow-fault scenario: client timed out and retried, but both writes landed
    events = [
        _call("write_file", 1), _result("write_file", 1, ok=True),
        _call("write_file", 2), _result("write_file", 2, ok=True),
    ]
    dupes = analyze(events)["duplicate_writes"]
    assert len(dupes) == 1
    assert dupes[0].verdict == "double_executed"
    assert dupes[0].executed_ok == 2


def test_replayed_after_fault_when_retry_is_identical():
    # short-circuit timeout: first call never reached the server, retry did
    events = [
        _call("write_file", 1), _fault("write_file", 1),
        _call("write_file", 2), _result("write_file", 2, ok=True),
    ]
    dupes = analyze(events)["duplicate_writes"]
    assert len(dupes) == 1
    assert dupes[0].verdict == "replayed_after_fault"
    assert dupes[0].executed_ok == 1


def test_no_finding_for_read_like_tools():
    events = [
        _call("read_file", 1), _result("read_file", 1),
        _call("read_file", 2), _result("read_file", 2),
    ]
    assert analyze(events)["duplicate_writes"] == []


def test_no_finding_when_arguments_differ():
    events = [
        _call("write_file", 1, args_hash="aaaa1111"), _result("write_file", 1),
        _call("write_file", 2, args_hash="bbbb2222"), _result("write_file", 2),
    ]
    assert analyze(events)["duplicate_writes"] == []


def test_no_finding_for_single_write():
    events = [_call("write_file", 1), _result("write_file", 1)]
    assert analyze(events)["duplicate_writes"] == []


def test_no_finding_when_duplicate_write_never_succeeded_and_no_fault():
    # two identical writes, both failed at the real server, no fault involved:
    # nothing double-executed and not our fault story
    events = [
        _call("write_file", 1), _result("write_file", 1, ok=False),
        _call("write_file", 2), _result("write_file", 2, ok=False),
    ]
    assert analyze(events)["duplicate_writes"] == []


def test_three_identical_ok_writes_counted():
    events = []
    for i in (1, 2, 3):
        events += [_call("delete_row", i), _result("delete_row", i)]
    dupes = analyze(events)["duplicate_writes"]
    assert dupes[0].verdict == "double_executed"
    assert dupes[0].calls == 3
    assert dupes[0].executed_ok == 3


def test_old_logs_without_args_hash_produce_no_findings():
    # recordings from older mcp-chaos have no args_hash; never guess
    events = [
        Event(t=0.0, kind="tool_call", tool="write_file", detail={"id": 1}),
        _result("write_file", 1),
        Event(t=0.0, kind="tool_call", tool="write_file", detail={"id": 2}),
        _result("write_file", 2),
    ]
    assert analyze(events)["duplicate_writes"] == []


def test_is_write_like_matches_verb_tokens_not_substrings():
    assert is_write_like("write_file")
    assert is_write_like("create_issue")
    assert is_write_like("deleteRow")
    assert is_write_like("files/update")
    assert not is_write_like("read_file")
    assert not is_write_like("get_settings")  # "set" must not match inside a word
    assert not is_write_like("list_directory")
