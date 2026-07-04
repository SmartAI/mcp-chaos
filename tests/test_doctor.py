"""Tests for `mcp-chaos doctor`: check an MCP client config before any agent runs.

Uses the real mock server for the healthy path, a nonexistent binary for the
broken path, and a sleeping process for the unresponsive path.
"""

import json
import os
import sys

from mcp_chaos.doctor import diagnose, parse_config, render_text

ROOT = os.path.dirname(os.path.dirname(__file__))
MOCK = os.path.join(ROOT, "tests", "mock_server.py")
MOCK_CMD = f"{sys.executable} {MOCK}"


def _config(tmp_path, servers):
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({"mcpServers": servers}))
    return str(p)


# --- config parsing ---


def test_parses_command_and_args_shape(tmp_path):
    path = _config(tmp_path, {
        "fs": {"command": "npx", "args": ["-y", "server-filesystem", "/tmp"],
               "env": {"DEBUG": "1"}},
    })
    specs = parse_config(path)
    assert specs[0].name == "fs"
    assert specs[0].argv == ["npx", "-y", "server-filesystem", "/tmp"]
    assert specs[0].env == {"DEBUG": "1"}


def test_skips_http_servers_but_reports_them(tmp_path):
    path = _config(tmp_path, {
        "hosted": {"url": "https://example.com/mcp"},
        "local": {"command": "echo"},
    })
    specs = parse_config(path)
    by_name = {s.name: s for s in specs}
    assert by_name["hosted"].skipped_reason  # not checkable yet, but visible
    assert not by_name["local"].skipped_reason


# --- live checks ---


def test_healthy_server_reports_tools_and_tokens(tmp_path):
    path = _config(tmp_path, {"mock": {"command": sys.executable, "args": [MOCK]}})
    result = diagnose(path, timeout=10)
    server = result["servers"][0]
    assert server["ok"] is True
    assert server["tools"] == ["get_order", "merge_pull_request"]
    assert server["tokens"] > 0
    assert server["startup_ms"] >= 0
    assert result["problems"] == 0


def test_broken_command_is_a_problem(tmp_path):
    path = _config(tmp_path, {
        "bad": {"command": "definitely-not-a-real-binary-xyz"},
    })
    result = diagnose(path, timeout=10)
    assert result["servers"][0]["ok"] is False
    assert result["servers"][0]["error"]
    assert result["problems"] == 1


def test_unresponsive_server_times_out(tmp_path):
    path = _config(tmp_path, {
        "hang": {"command": sys.executable, "args": ["-c", "import time; time.sleep(60)"]},
    })
    result = diagnose(path, timeout=2)
    assert result["servers"][0]["ok"] is False
    assert "timed out" in result["servers"][0]["error"]


def test_tool_name_collisions_across_servers(tmp_path):
    path = _config(tmp_path, {
        "a": {"command": sys.executable, "args": [MOCK]},
        "b": {"command": sys.executable, "args": [MOCK]},
    })
    result = diagnose(path, timeout=10)
    assert ("get_order", ["a", "b"]) in result["collisions"]


def test_totals_summarize_the_whole_config(tmp_path):
    path = _config(tmp_path, {"mock": {"command": sys.executable, "args": [MOCK]}})
    result = diagnose(path, timeout=10)
    assert result["total_tools"] == 2
    assert result["total_tokens"] > 0


# --- rendering and exit codes ---


def test_render_marks_health_and_collisions(tmp_path):
    path = _config(tmp_path, {
        "a": {"command": sys.executable, "args": [MOCK]},
        "b": {"command": sys.executable, "args": [MOCK]},
        "bad": {"command": "definitely-not-a-real-binary-xyz"},
    })
    text = render_text(diagnose(path, timeout=10))
    assert "✔" in text and "✘" in text
    assert "get_order" in text  # the collision is named


def test_cli_exits_1_when_a_server_is_broken(tmp_path):
    from mcp_chaos.cli import main
    path = _config(tmp_path, {"bad": {"command": "definitely-not-a-real-binary-xyz"}})
    assert main(["doctor", path]) == 1


def test_cli_exits_0_when_healthy(tmp_path):
    from mcp_chaos.cli import main
    path = _config(tmp_path, {"mock": {"command": sys.executable, "args": [MOCK]}})
    assert main(["doctor", path]) == 0
