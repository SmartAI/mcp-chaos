"""Command-line entry point for mcp-chaos."""

from __future__ import annotations

import argparse
import asyncio
import sys

from . import __version__, config, proxy, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-chaos",
        description="Chaos engineering for AI agents — a fault-injecting MCP proxy.",
    )
    parser.add_argument("--version", action="version", version=f"mcp-chaos {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run the proxy in front of a real MCP server")
    run.add_argument("-c", "--config", required=True, help="path to faults.yaml")
    run.add_argument("--record", default="run.jsonl", help="event log output path")
    run.add_argument("--cassette",
                     help="also capture every agent-visible response to this "
                          "file, for later hermetic `replay`")

    rpl = sub.add_parser("replay",
                         help="serve a recorded cassette as a standalone MCP "
                              "server — no real server, deterministic, zero cost")
    rpl.add_argument("cassette", help="path to a cassette recorded by `run --cassette`")

    doc = sub.add_parser(
        "doctor",
        help="check an MCP client config: do the servers launch, collide, or "
             "bloat your context — before any agent runs?")
    doc.add_argument("config",
                     help="client config with an mcpServers section "
                          "(.mcp.json, claude_desktop_config.json, Cursor mcp.json)")
    doc.add_argument("--timeout", type=float, default=20,
                     help="seconds to wait per server (default 20)")

    cor = sub.add_parser(
        "correlate",
        help="correlate a run log with the agent's transcript: did it claim "
             "success while the tool failed?")
    cor.add_argument("record", help="path to a run.jsonl produced by `run`")
    cor.add_argument("transcript",
                     help="the agent's transcript: a Claude Code session .jsonl, "
                          "or a plain-text file holding the final answer")
    cor.add_argument("--fail-on", choices=["claimed-success"],
                     help="exit 1 if the agent claimed success over a tool "
                          "that never worked")

    rep = sub.add_parser("report", help="render an HTML report from a run log")
    rep.add_argument("record", help="path to a run.jsonl produced by `run`")
    rep.add_argument("-o", "--out", default="report.html", help="HTML output path")
    rep.add_argument(
        "--fail-on", choices=["runaway", "retried", "duplicate-write"], action="append",
        help="exit 1 if any finding reaches this verdict; repeat the flag to "
             "gate on several (retried is stricter than runaway: any retry "
             "fails; duplicate-write: an identical write was re-sent after a "
             "fault or double-executed)",
    )

    args = parser.parse_args(argv)

    if args.cmd == "run":
        return _run(args)
    if args.cmd == "replay":
        return _replay(args)
    if args.cmd == "doctor":
        return _doctor(args)
    if args.cmd == "correlate":
        return _correlate(args)
    if args.cmd == "report":
        return _report(args)
    return 1


def _doctor(args) -> int:
    from .doctor import diagnose, render_text

    result = diagnose(args.config, timeout=args.timeout)
    print(render_text(result))
    return 1 if result["problems"] else 0


def _correlate(args) -> int:
    from .correlate import correlate, summary

    result = correlate(args.record, args.transcript)
    print(summary(result))
    if args.fail_on == "claimed-success" and result["verdict"] == "claimed_success":
        return 1
    return 0


def _run(args) -> int:
    from .cassette import CassetteWriter
    from .recorder import Recorder

    cfg = config.load(args.config)
    recorder = Recorder(args.record, command=cfg.command, faults=len(cfg.faults))
    cassette = CassetteWriter(args.cassette) if args.cassette else None
    # Startup notice goes to stderr so it never corrupts the stdio JSON-RPC stream.
    print(f"mcp-chaos: proxying `{cfg.command}` with {len(cfg.faults)} fault(s)",
          file=sys.stderr)
    return asyncio.run(proxy.run(cfg, recorder, cassette))


def _replay(args) -> int:
    from .cassette import Cassette, serve

    cassette = Cassette.load(args.cassette)
    print(f"mcp-chaos: replaying {args.cassette} — no real server behind this",
          file=sys.stderr)
    serve(cassette, sys.stdin, sys.stdout)
    return 0


def _report(args) -> int:
    import json

    from .recorder import Event

    events = []
    with open(args.record) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(Event(**json.loads(line)))
    with open(args.out, "w") as f:
        f.write(report.render(events))
    print(f"mcp-chaos: wrote {args.out}", file=sys.stderr)

    if args.fail_on:
        from .checks import analyze, summary_line

        gates = set(args.fail_on)
        failing = set()
        if "retried" in gates:
            failing = {"runaway", "retried"}  # stricter gate: any retry fails
        elif "runaway" in gates:
            failing = {"runaway"}
        result = analyze(events)
        tripped = [f for f in result["findings"] if f.verdict in failing]
        dupes = result["duplicate_writes"] if "duplicate-write" in gates else []
        if tripped or dupes:
            print(f"mcp-chaos: {summary_line(result)}", file=sys.stderr)
            for f in tripped:
                print(f"mcp-chaos: FAIL {f.tool} ({f.fault_type}): "
                      f"{f.verdict}, {f.retries} retries after fault", file=sys.stderr)
            for d in dupes:
                print(f"mcp-chaos: FAIL {d.tool} (args {d.args_hash}): "
                      f"{d.verdict}, sent {d.calls}x, executed ok {d.executed_ok}x",
                      file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
