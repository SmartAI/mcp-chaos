"""Streamable HTTP relay: stdio on the agent side, a hosted MCP server upstream.

The agent still speaks stdio to mcp-chaos — the one-line config insert works in
every client — while `server.url` makes the proxy POST each JSON-RPC message to
the hosted endpoint. Fault injection, recording, and cassette capture are the
same as the stdio proxy; only the upstream transport differs.

Transport notes (Streamable HTTP, MCP 2025-03-26+):
- one POST per message; responses arrive as application/json or as a
  text/event-stream whose data events are JSON-RPC messages (notifications are
  forwarded to the agent as they arrive, the matching response ends the call)
- the Mcp-Session-Id response header from initialize is echoed on every
  subsequent request; MCP-Protocol-Version is sent once negotiated
- the optional GET listening stream (server-initiated requests) is not opened;
  fault matching only needs request/response traffic
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time

import httpx

from .cassette import CassetteWriter, call_key
from .config import Config
from .faults import DELAY, MUTATE, SHORT_CIRCUIT, FaultEngine, mutate_response, short_circuit_response
from .proxy import _cassette_log, _client_writer, _dump, _parse, _stdin_reader
from .recorder import Recorder


async def run(config: Config, recorder: Recorder,
              cassette: CassetteWriter | None = None) -> int:
    engine = FaultEngine(config.faults)
    client_in = await _stdin_reader()
    out: asyncio.Queue[bytes | None] = asyncio.Queue()
    session = {"id": None, "protocol": None}
    reqmeta: dict = {}
    tasks: set[asyncio.Task] = set()

    writer = asyncio.create_task(_client_writer(out))
    async with httpx.AsyncClient(timeout=config.http_timeout,
                                 headers=config.headers) as http:
        while True:
            line = await client_in.readline()
            if not line:
                break
            msg = _parse(line)
            if msg is None:
                continue
            if cassette is not None and msg.get("id") is not None and msg.get("method"):
                params = msg.get("params") or {}
                tool_name = params.get("name") if msg["method"] == "tools/call" else None
                reqmeta[msg["id"]] = (msg["method"], tool_name,
                                      call_key(msg["method"], params))
            task = asyncio.create_task(
                _handle(msg, http, config, engine, recorder, out, session,
                        cassette, reqmeta))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        if tasks:
            await asyncio.wait(tasks, timeout=config.http_timeout)

    await out.put(None)
    await writer
    recorder.flush()
    return 0


async def _handle(msg, http, config, engine, recorder, out, session,
                  cassette, reqmeta) -> None:
    method = msg.get("method")
    req_id = msg.get("id")
    fault = None

    if method == "tools/call":
        params = msg.get("params") or {}
        tool = params.get("name", "<unknown>")
        args = json.dumps(params.get("arguments"), sort_keys=True)
        recorder.log("tool_call", tool=tool, id=req_id, args_chars=len(args),
                     args_hash=hashlib.md5(args.encode()).hexdigest()[:8])
        fault = engine.decide(tool)
        if fault is not None and fault.type in SHORT_CIRCUIT:
            recorder.log("fault", tool=tool, type=fault.type, id=req_id,
                         mode="short_circuit")
            response = short_circuit_response(fault, req_id)
            _cassette_log(cassette, reqmeta, req_id, response)
            await out.put(_dump(response))
            return
        if fault is not None and fault.type in DELAY:
            recorder.log("fault", tool=tool, type=fault.type, id=req_id,
                         delay_ms=fault.delay_ms)
            await asyncio.sleep(fault.delay_ms / 1000)
        elif fault is not None and fault.type in MUTATE:
            recorder.log("fault", tool=tool, type=fault.type, id=req_id, mode="mutate")

    t0 = time.monotonic()
    try:
        response = await _post(msg, http, config, session, out)
    except httpx.HTTPError as e:
        if req_id is None:
            return  # a failed notification has nobody to tell
        if method == "tools/call":
            recorder.log("tool_result", tool=msg["params"].get("name"), id=req_id,
                         ok=False, ms=round((time.monotonic() - t0) * 1000),
                         chars=0, code=-32000)
        error = {"jsonrpc": "2.0", "id": req_id,
                 "error": {"code": -32000,
                           "message": f"mcp-chaos: upstream HTTP request failed: {e}"}}
        _cassette_log(cassette, reqmeta, req_id, error)
        await out.put(_dump(error))
        return
    if response is None:
        return  # notification accepted upstream, nothing to relay

    raw = json.dumps(response)
    if method == "initialize":
        session["protocol"] = (response.get("result") or {}).get("protocolVersion")
    elif method == "tools/list":
        tools = [t.get("name", "") for t in
                 ((response.get("result") or {}).get("tools") or [])]
        recorder.log("tools_list", count=len(tools), chars=len(raw), tools=tools)
    elif method == "tools/call":
        ok = "error" not in response and not (response.get("result") or {}).get("isError")
        detail = {"id": req_id, "ok": ok,
                  "ms": round((time.monotonic() - t0) * 1000), "chars": len(raw)}
        if "error" in response:
            detail["code"] = response["error"].get("code")
        recorder.log("tool_result", tool=msg["params"].get("name"), **detail)

    if fault is not None and fault.type in MUTATE:
        recorder.log("response", type=fault.type, id=req_id, mode="mutated")
        response = mutate_response(fault, response)
    _cassette_log(cassette, reqmeta, req_id, response)
    await out.put(_dump(response))


async def _post(msg, http, config, session, out) -> dict | None:
    """POST one message upstream; returns the response for requests, None for
    notifications. Streamed notifications are forwarded as they arrive."""
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    if session["id"]:
        headers["Mcp-Session-Id"] = session["id"]
    if session["protocol"]:
        headers["MCP-Protocol-Version"] = session["protocol"]

    req_id = msg.get("id")
    async with http.stream("POST", config.url, json=msg, headers=headers) as resp:
        resp.raise_for_status()
        if sid := resp.headers.get("Mcp-Session-Id"):
            session["id"] = sid
        if req_id is None:
            return None  # 202 Accepted for notifications
        ctype = resp.headers.get("Content-Type", "")
        if "text/event-stream" not in ctype:
            return json.loads(await resp.aread())

        data_lines: list[str] = []
        async for line in resp.aiter_lines():
            if line == "":  # blank line ends one SSE event
                if not data_lines:
                    continue
                event, data_lines = "\n".join(data_lines), []
                try:
                    streamed = json.loads(event)
                except json.JSONDecodeError:
                    continue
                if isinstance(streamed, dict) and streamed.get("id") == req_id:
                    return streamed
                await out.put(_dump(streamed))  # notification/progress: pass along
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            # other SSE fields (event:, id:, retry:, comments) are irrelevant here
    raise httpx.TransportError(
        f"stream ended without a response to request {req_id!r}")


def notice(config: Config) -> None:
    print(f"mcp-chaos: relaying stdio ⇄ {config.url} "
          f"with {len(config.faults)} fault(s)", file=sys.stderr)
