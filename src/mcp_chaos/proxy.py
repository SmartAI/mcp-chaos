"""Transparent MCP stdio proxy with fault injection.

Relays newline-delimited JSON-RPC between an MCP client (the agent) and the real
MCP server, spawned as a child process. Only `tools/call` traffic is inspected;
everything else (initialize, tools/list, notifications) passes through untouched,
which keeps the proxy protocol-version-agnostic.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
import sys
import time

from .cassette import CassetteWriter, call_key
from .config import Config
from .faults import DELAY, MUTATE, SHORT_CIRCUIT, FaultEngine, mutate_response, short_circuit_response
from .recorder import Recorder


async def run(config: Config, recorder: Recorder,
              cassette: CassetteWriter | None = None) -> int:
    engine = FaultEngine(config.faults)
    child = await asyncio.create_subprocess_exec(
        *shlex.split(config.command),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        # stderr inherits so the real server's logs stay visible to the user.
    )

    client_in = await _stdin_reader()
    out: asyncio.Queue[bytes | None] = asyncio.Queue()
    pending: dict = {}  # request id -> mutate Fault, awaiting the real response
    inflight: dict = {}  # request id -> (tool, monotonic send time), for tool_result capture
    listing: set = set()  # request ids of in-flight tools/list calls
    reqmeta: dict = {}  # request id -> (method, tool, cassette key), when recording one

    writer = asyncio.create_task(_client_writer(out))
    to_child = asyncio.create_task(
        _client_to_child(client_in, child, engine, pending, out, recorder, inflight,
                         listing, cassette, reqmeta)
    )
    from_child = asyncio.create_task(
        _child_to_client(child, pending, out, recorder, inflight, listing,
                         cassette, reqmeta)
    )

    await asyncio.wait([to_child, from_child], return_when=asyncio.FIRST_COMPLETED)
    await out.put(None)  # signal writer to stop
    await writer
    for task in (to_child, from_child):
        task.cancel()

    recorder.flush()
    if child.returncode is None:
        child.terminate()
    return child.returncode or 0


async def _client_to_child(client_in, child, engine, pending, out, recorder, inflight,
                           listing, cassette, reqmeta):
    while True:
        line = await client_in.readline()
        if not line:
            break
        msg = _parse(line)
        method = msg.get("method") if msg is not None else None
        if method == "tools/list" and msg.get("id") is not None:
            listing.add(msg["id"])
        if cassette is not None and msg is not None and msg.get("id") is not None and method:
            params = msg.get("params") or {}
            tool_name = params.get("name") if method == "tools/call" else None
            reqmeta[msg["id"]] = (method, tool_name, call_key(method, params))
        if msg is None or method != "tools/call":
            child.stdin.write(line)
            await child.stdin.drain()
            continue

        params = msg.get("params") or {}
        tool = params.get("name", "<unknown>")
        req_id = msg.get("id")
        args = json.dumps(params.get("arguments"), sort_keys=True)
        recorder.log("tool_call", tool=tool, id=req_id, args_chars=len(args),
                     args_hash=hashlib.md5(args.encode()).hexdigest()[:8])
        fault = engine.decide(tool)

        if fault is None:
            inflight[req_id] = (tool, time.monotonic())
            child.stdin.write(line)
            await child.stdin.drain()
        elif fault.type in SHORT_CIRCUIT:
            # Never reaches the real server: a `fault` event only, no tool_result.
            recorder.log("fault", tool=tool, type=fault.type, id=req_id, mode="short_circuit")
            response = short_circuit_response(fault, req_id)
            _cassette_log(cassette, reqmeta, req_id, response)
            await out.put(_dump(response))
        elif fault.type in DELAY:
            recorder.log("fault", tool=tool, type=fault.type, id=req_id, delay_ms=fault.delay_ms)
            await asyncio.sleep(fault.delay_ms / 1000)
            inflight[req_id] = (tool, time.monotonic())
            child.stdin.write(line)
            await child.stdin.drain()
        elif fault.type in MUTATE:
            recorder.log("fault", tool=tool, type=fault.type, id=req_id, mode="mutate")
            pending[req_id] = fault
            inflight[req_id] = (tool, time.monotonic())
            child.stdin.write(line)
            await child.stdin.drain()


async def _child_to_client(child, pending, out, recorder, inflight, listing,
                           cassette, reqmeta):
    while True:
        line = await child.stdout.readline()
        if not line:
            break
        msg = _parse(line)
        rid = msg.get("id") if msg is not None else None
        if rid is not None and rid in listing:
            listing.discard(rid)
            tools = [t.get("name", "") for t in ((msg.get("result") or {}).get("tools") or [])]
            recorder.log("tools_list", count=len(tools), chars=len(line), tools=tools)
        if rid is not None and rid in inflight:
            # What the real server did, even when a mutate fault rewrites what
            # the agent gets to see.
            tool, t0 = inflight.pop(rid)
            ok = "error" not in msg and not (msg.get("result") or {}).get("isError")
            detail = {"id": rid, "ok": ok, "ms": round((time.monotonic() - t0) * 1000),
                      "chars": len(line)}
            if "error" in msg:
                detail["code"] = msg["error"].get("code")
            recorder.log("tool_result", tool=tool, **detail)
        if msg is not None and rid in pending:
            fault = pending.pop(rid)
            recorder.log("response", type=fault.type, id=rid, mode="mutated")
            mutated = mutate_response(fault, msg)
            _cassette_log(cassette, reqmeta, rid, mutated)
            await out.put(_dump(mutated))
        else:
            if msg is not None:
                _cassette_log(cassette, reqmeta, rid, msg)
            await out.put(line)


def _cassette_log(cassette, reqmeta, rid, response: dict) -> None:
    """Capture the response as the agent saw it (real, faulted, or mutated)."""
    if cassette is None or rid not in reqmeta:
        return
    method, tool, key = reqmeta.pop(rid)
    body = {k: response[k] for k in ("result", "error") if k in response}
    if body:
        cassette.log(method, tool, key, body)


async def _client_writer(out: asyncio.Queue):
    while True:
        chunk = await out.get()
        if chunk is None:
            break
        sys.stdout.buffer.write(chunk if chunk.endswith(b"\n") else chunk + b"\n")
        sys.stdout.buffer.flush()


async def _stdin_reader() -> asyncio.StreamReader:
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    return reader


def _parse(line: bytes) -> dict | None:
    try:
        obj = json.loads(line)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _dump(msg: dict) -> bytes:
    return json.dumps(msg).encode() + b"\n"
