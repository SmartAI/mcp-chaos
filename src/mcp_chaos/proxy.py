"""Transparent MCP stdio proxy with fault injection.

Relays newline-delimited JSON-RPC between an MCP client (the agent) and the real
MCP server, spawned as a child process. Only `tools/call` traffic is inspected;
everything else (initialize, tools/list, notifications) passes through untouched,
which keeps the proxy protocol-version-agnostic.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import sys

from .config import Config
from .faults import DELAY, MUTATE, SHORT_CIRCUIT, FaultEngine, mutate_response, short_circuit_response
from .recorder import Recorder


async def run(config: Config, recorder: Recorder) -> int:
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

    writer = asyncio.create_task(_client_writer(out))
    to_child = asyncio.create_task(
        _client_to_child(client_in, child, engine, pending, out, recorder)
    )
    from_child = asyncio.create_task(
        _child_to_client(child, pending, out, recorder)
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


async def _client_to_child(client_in, child, engine, pending, out, recorder):
    while True:
        line = await client_in.readline()
        if not line:
            break
        msg = _parse(line)
        if msg is None or msg.get("method") != "tools/call":
            child.stdin.write(line)
            await child.stdin.drain()
            continue

        tool = (msg.get("params") or {}).get("name", "<unknown>")
        req_id = msg.get("id")
        recorder.log("tool_call", tool=tool, id=req_id)
        fault = engine.decide(tool)

        if fault is None:
            child.stdin.write(line)
            await child.stdin.drain()
        elif fault.type in SHORT_CIRCUIT:
            recorder.log("fault", tool=tool, type=fault.type, id=req_id, mode="short_circuit")
            await out.put(_dump(short_circuit_response(fault, req_id)))
        elif fault.type in DELAY:
            recorder.log("fault", tool=tool, type=fault.type, id=req_id, delay_ms=fault.delay_ms)
            await asyncio.sleep(fault.delay_ms / 1000)
            child.stdin.write(line)
            await child.stdin.drain()
        elif fault.type in MUTATE:
            recorder.log("fault", tool=tool, type=fault.type, id=req_id, mode="mutate")
            pending[req_id] = fault
            child.stdin.write(line)
            await child.stdin.drain()


async def _child_to_client(child, pending, out, recorder):
    while True:
        line = await child.stdout.readline()
        if not line:
            break
        msg = _parse(line)
        if msg is not None and msg.get("id") in pending:
            fault = pending.pop(msg["id"])
            recorder.log("response", type=fault.type, id=msg["id"], mode="mutated")
            await out.put(_dump(mutate_response(fault, msg)))
        else:
            await out.put(line)


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
