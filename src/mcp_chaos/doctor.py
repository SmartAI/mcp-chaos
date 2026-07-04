"""MCP config doctor: do your servers launch, collide, or bloat your context —
before the agent runs?

Reads a client config in the `mcpServers` shape shared by Claude Code,
Claude Desktop, and Cursor, launches each stdio server, and speaks just enough
MCP (initialize → tools/list) to answer three questions per server:

- does it start and respond at all?
- what tools does it advertise, and what do their definitions cost in context
  tokens (chars/4, same heuristic as the efficiency profile)?
- do tool names collide with another server's?

HTTP/SSE entries are reported but not checked (stdio only today).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field

from .efficiency import CHARS_PER_TOKEN


@dataclass
class ServerSpec:
    name: str
    argv: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)
    skipped_reason: str = ""


def parse_config(path: str) -> list[ServerSpec]:
    with open(path) as f:
        raw = json.load(f)
    servers = raw.get("mcpServers", raw)
    specs = []
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("command"):
            specs.append(ServerSpec(
                name=name,
                argv=[entry["command"], *entry.get("args", [])],
                env=entry.get("env", {}),
            ))
        elif entry.get("url"):
            specs.append(ServerSpec(
                name=name,
                skipped_reason=f"HTTP transport not checked yet ({entry['url']})",
            ))
        else:
            specs.append(ServerSpec(name=name, skipped_reason="no command or url"))
    return specs


def diagnose(path: str, timeout: float = 20) -> dict:
    """Check every server in the config; pure data out, rendering separate."""
    specs = parse_config(path)
    results = asyncio.run(_check_all(specs, timeout))

    tool_owners: dict[str, list[str]] = {}
    for r in results:
        for t in r.get("tools") or []:
            tool_owners.setdefault(t, []).append(r["name"])
    collisions = sorted(
        (tool, owners) for tool, owners in tool_owners.items() if len(owners) > 1
    )

    checked = [r for r in results if not r["skipped"]]
    return {
        "servers": results,
        "collisions": collisions,
        "problems": sum(1 for r in checked if not r["ok"]),
        "total_tools": sum(len(r.get("tools") or []) for r in results),
        "total_tokens": sum(r.get("tokens") or 0 for r in results),
    }


async def _check_all(specs: list[ServerSpec], timeout: float) -> list[dict]:
    return list(await asyncio.gather(*(_check(s, timeout) for s in specs)))


async def _check(spec: ServerSpec, timeout: float) -> dict:
    result = {"name": spec.name, "ok": False, "skipped": bool(spec.skipped_reason),
              "error": spec.skipped_reason, "tools": [], "tokens": 0, "startup_ms": 0}
    if spec.skipped_reason:
        return result

    t0 = time.monotonic()
    try:
        child = await asyncio.create_subprocess_exec(
            *spec.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, **spec.env},
        )
    except (OSError, ValueError) as e:
        result["error"] = f"launch failed: {e}"
        return result

    try:
        listing = await asyncio.wait_for(_handshake(child), timeout)
        tools = (listing.get("result") or {}).get("tools") or []
        result.update(
            ok=True, error="",
            tools=sorted(t.get("name", "") for t in tools),
            tokens=len(json.dumps(tools)) // CHARS_PER_TOKEN,
            startup_ms=round((time.monotonic() - t0) * 1000),
        )
    except asyncio.TimeoutError:
        result["error"] = f"timed out after {timeout:g}s waiting for initialize/tools list"
    except Exception as e:  # dead pipe, garbage output, early exit, ...
        result["error"] = f"handshake failed: {e}"
    finally:
        if child.returncode is None:
            child.terminate()
            try:
                await asyncio.wait_for(child.wait(), 3)
            except asyncio.TimeoutError:
                child.kill()
    return result


async def _handshake(child) -> dict:
    """initialize → notifications/initialized → tools/list, returning the listing."""
    await _send(child, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "mcp-chaos-doctor", "version": "0"},
    }})
    await _read_response(child, 1)
    await _send(child, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    await _send(child, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    return await _read_response(child, 2)


async def _send(child, msg: dict) -> None:
    child.stdin.write(json.dumps(msg).encode() + b"\n")
    await child.stdin.drain()


async def _read_response(child, want_id) -> dict:
    while True:
        line = await child.stdout.readline()
        if not line:
            raise RuntimeError("server closed its stdout during the handshake")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue  # log noise on stdout; keep reading
        if isinstance(msg, dict) and msg.get("id") == want_id:
            if "error" in msg:
                raise RuntimeError(msg["error"].get("message", "server returned an error"))
            return msg


def render_text(result: dict) -> str:
    lines = []
    for r in result["servers"]:
        if r["skipped"]:
            lines.append(f"- {r['name']}: skipped — {r['error']}")
        elif r["ok"]:
            lines.append(f"✔ {r['name']}: {len(r['tools'])} tools · "
                         f"~{r['tokens']} tokens of definitions · "
                         f"ready in {r['startup_ms']} ms")
        else:
            lines.append(f"✘ {r['name']}: {r['error']}")
    for tool, owners in result["collisions"]:
        lines.append(f"⚠ tool name collision: {tool} ({', '.join(owners)})")
    lines.append(f"{len(result['servers'])} server(s) · {result['total_tools']} tools · "
                 f"~{result['total_tokens']} tokens of tool definitions per session")
    if result["problems"]:
        lines.append(f"{result['problems']} problem(s) found")
    return "\n".join(lines)
