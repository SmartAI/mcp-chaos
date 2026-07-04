"""Render a recorded run into a single self-contained HTML timeline."""

from __future__ import annotations

import html
import json

from .checks import analyze, summary_line
from .efficiency import profile
from .recorder import Event

_COLORS = {"tool_call": "#3b82f6", "fault": "#ef4444", "response": "#f59e0b",
           "session_start": "#6b7280", "tools_list": "#8b5cf6", "tool_result": "#10b981"}
_VERDICT_COLORS = {"runaway": "#ef4444", "retried": "#f59e0b", "stopped": "#6b7280",
                   "double_executed": "#ef4444", "replayed_after_fault": "#f59e0b"}


def render(events: list[Event], title: str = "mcp-chaos run") -> str:
    rows = []
    for e in events:
        color = _COLORS.get(e.kind, "#888")
        detail = ", ".join(f"{k}={v}" for k, v in e.detail.items())
        rows.append(
            f'<tr><td class="t">{e.t:.3f}s</td>'
            f'<td><span class="dot" style="background:{color}"></span>{html.escape(e.kind)}</td>'
            f'<td>{html.escape(e.tool or "")}</td>'
            f'<td class="d">{html.escape(detail)}</td></tr>'
        )

    result = analyze(events)
    finding_rows = []
    for f in result["findings"]:
        vc = _VERDICT_COLORS.get(f.verdict, "#888")
        finding_rows.append(
            f'<tr><td>{html.escape(f.tool)}</td><td>{html.escape(f.fault_type)}</td>'
            f'<td>{f.retries}</td>'
            f'<td><span class="badge" style="background:{vc}">{f.verdict}</span></td></tr>'
        )

    dupe_rows = []
    for d in result["duplicate_writes"]:
        vc = _VERDICT_COLORS.get(d.verdict, "#888")
        dupe_rows.append(
            f'<tr><td>{html.escape(d.tool)}</td><td class="d">{html.escape(d.args_hash)}</td>'
            f'<td>{d.calls}</td><td>{d.executed_ok}</td>'
            f'<td><span class="badge" style="background:{vc}">{d.verdict}</span></td></tr>'
        )

    return _TEMPLATE.format(
        title=html.escape(title),
        summary=html.escape(summary_line(result)),
        findings="\n".join(finding_rows) or '<tr><td colspan="4">no faults injected</td></tr>',
        dupes="\n".join(dupe_rows) or '<tr><td colspan="5">none detected</td></tr>',
        efficiency=_efficiency_section(events),
        rows="\n".join(rows),
        data=json.dumps([e.__dict__ for e in events]),
    )


def _efficiency_section(events: list[Event]) -> str:
    p = profile(events)
    if not p["has_data"]:
        return ('<p class="d">no efficiency data in this log — it was recorded by an '
                'older mcp-chaos without traffic capture.</p>')

    parts = []
    if p["advertised"] is not None:
        tax = (f'{p["advertised"]} tools advertised · ~{p["listing_tokens"]} tokens '
               f'of tool definitions loaded per session')
        if p["unused"]:
            tax += f' · {len(p["unused"])} never called: {", ".join(p["unused"])}'
        parts.append(f'<div class="summary">{html.escape(tax)}</div>')

    tool_rows = []
    for name, s in sorted(p["tools"].items()):
        tool_rows.append(
            f'<tr><td>{html.escape(name)}</td><td>{s["calls"]}</td><td>{s["errors"]}</td>'
            f'<td>{s["avg_ms"]} ms</td><td>~{s["result_tokens"]} tokens</td>'
            f'<td>{s["corrected_retries"]}</td></tr>'
        )
    parts.append(
        '<table><thead><tr><th>Tool</th><th>Calls</th><th>Errors</th>'
        '<th>Avg latency</th><th>Results returned</th><th>Corrected retries</th>'
        '</tr></thead><tbody>\n' + "\n".join(tool_rows) + '\n</tbody></table>'
    )
    return "\n".join(parts)


_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font: 14px/1.5 -apple-system, system-ui, sans-serif; margin: 2rem; color: #111; }}
  h1 {{ font-size: 1.3rem; }}
  .summary {{ color: #555; margin-bottom: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; }}
  th {{ color: #666; font-weight: 600; }}
  .t {{ font-variant-numeric: tabular-nums; color: #888; white-space: nowrap; }}
  .d {{ color: #444; font-family: ui-monospace, monospace; font-size: 12px; }}
  .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%;
          margin-right: 6px; vertical-align: middle; }}
  .badge {{ color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 12px; }}
  h2 {{ font-size: 1rem; margin-top: 1.5rem; color: #333; }}
</style></head>
<body>
  <h1>{title}</h1>
  <div class="summary">{summary}</div>

  <h2>Resilience findings</h2>
  <table>
    <thead><tr><th>Tool</th><th>Fault</th><th>Retries after fault</th><th>Verdict</th></tr></thead>
    <tbody>
{findings}
    </tbody>
  </table>

  <h2>Duplicate writes</h2>
  <table>
    <thead><tr><th>Tool</th><th>Args hash</th><th>Times sent</th>
    <th>Executed ok</th><th>Verdict</th></tr></thead>
    <tbody>
{dupes}
    </tbody>
  </table>

  <h2>MCP efficiency</h2>
{efficiency}

  <h2>Timeline</h2>
  <table>
    <thead><tr><th>Time</th><th>Event</th><th>Tool</th><th>Detail</th></tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
  <script>window.__run = {data};</script>
</body></html>
"""
