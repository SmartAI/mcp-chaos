"""Tests for `mcp-chaos report --fail-on`, the CI exit-code gate."""

import json
from dataclasses import asdict

from mcp_chaos.checks import RUNAWAY_THRESHOLD
from mcp_chaos.cli import main
from mcp_chaos.recorder import Event


def _call(tool, **detail):
    return Event(t=0.0, kind="tool_call", tool=tool, detail=detail)


def _fault(tool, ftype="timeout", **detail):
    return Event(t=0.0, kind="fault", tool=tool, detail={"type": ftype, **detail})


def _result(tool, id, ok=True):
    return Event(t=0.0, kind="tool_result", tool=tool, detail={"id": id, "ok": ok})


RUNAWAY_RUN = [_call("merge"), _fault("merge")] + [_call("merge")] * RUNAWAY_THRESHOLD
RETRIED_RUN = [_call("merge"), _fault("merge"), _call("merge")]
STOPPED_RUN = [_call("merge"), _fault("merge")]
CLEAN_RUN = [_call("merge")]  # no faults at all
DUPLICATE_WRITE_RUN = [
    _call("write_file", id=1, args_hash="aaaa1111"), _fault("write_file", id=1),
    _call("write_file", id=2, args_hash="aaaa1111"), _result("write_file", 2),
]


def _report(tmp_path, events, *extra_args):
    record = tmp_path / "run.jsonl"
    record.write_text("".join(json.dumps(asdict(e)) + "\n" for e in events))
    out = tmp_path / "report.html"
    return main(["report", str(record), "-o", str(out), *extra_args])


def test_fail_on_runaway_exits_1_on_runaway(tmp_path):
    assert _report(tmp_path, RUNAWAY_RUN, "--fail-on", "runaway") == 1


def test_fail_on_runaway_exits_0_when_only_retried(tmp_path):
    assert _report(tmp_path, RETRIED_RUN, "--fail-on", "runaway") == 0


def test_fail_on_runaway_exits_0_on_clean_run(tmp_path):
    assert _report(tmp_path, CLEAN_RUN, "--fail-on", "runaway") == 0


def test_fail_on_retried_exits_1_on_retried(tmp_path):
    assert _report(tmp_path, RETRIED_RUN, "--fail-on", "retried") == 1


def test_fail_on_retried_exits_1_on_runaway(tmp_path):
    # "retried" is the strictest gate: any retry at all fails, runaway included.
    assert _report(tmp_path, RUNAWAY_RUN, "--fail-on", "retried") == 1


def test_fail_on_retried_exits_0_when_agent_stopped(tmp_path):
    assert _report(tmp_path, STOPPED_RUN, "--fail-on", "retried") == 0


def test_without_flag_behavior_unchanged(tmp_path):
    assert _report(tmp_path, RUNAWAY_RUN) == 0


def test_html_still_written_when_gate_trips(tmp_path):
    assert _report(tmp_path, RUNAWAY_RUN, "--fail-on", "runaway") == 1
    assert (tmp_path / "report.html").exists()


def test_tripped_findings_printed_to_stderr(tmp_path, capsys):
    _report(tmp_path, RUNAWAY_RUN, "--fail-on", "runaway")
    err = capsys.readouterr().err
    assert "merge" in err
    assert "runaway" in err


def test_fail_on_duplicate_write_exits_1(tmp_path):
    assert _report(tmp_path, DUPLICATE_WRITE_RUN, "--fail-on", "duplicate-write") == 1


def test_fail_on_duplicate_write_exits_0_when_retry_differs(tmp_path):
    # the retry changed its arguments — not a blind duplicate
    corrected = [
        _call("write_file", id=1, args_hash="aaaa1111"), _fault("write_file", id=1),
        _call("write_file", id=2, args_hash="bbbb2222"), _result("write_file", 2),
    ]
    assert _report(tmp_path, corrected, "--fail-on", "duplicate-write") == 0


def test_fail_on_runaway_ignores_duplicate_writes(tmp_path):
    assert _report(tmp_path, DUPLICATE_WRITE_RUN, "--fail-on", "runaway") == 0


def test_fail_on_is_repeatable(tmp_path):
    # gate on both concerns at once
    assert _report(tmp_path, DUPLICATE_WRITE_RUN,
                   "--fail-on", "runaway", "--fail-on", "duplicate-write") == 1
