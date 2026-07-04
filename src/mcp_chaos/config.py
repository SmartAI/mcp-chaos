"""Load and validate the YAML fault configuration."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

import yaml

FAULT_TYPES = {"timeout", "error", "rate_limit", "slow", "empty", "corrupt", "inject"}


@dataclass
class Fault:
    """A single fault rule matched against outgoing tool calls."""

    tool: str  # exact tool name or glob (e.g. "list_*")
    type: str
    after_calls: int = 1  # fire starting from the Nth matching call
    probability: float = 1.0  # 0.0–1.0
    payload: str | None = None  # text for `inject`
    delay_ms: int = 2000  # extra latency for `slow`

    def matches(self, tool_name: str) -> bool:
        return fnmatch.fnmatch(tool_name, self.tool)


@dataclass
class Config:
    command: str | None = None  # command that launches a stdio MCP server, or
    url: str | None = None  # a hosted server's Streamable HTTP endpoint
    headers: dict = field(default_factory=dict)  # extra HTTP headers (auth, ...)
    http_timeout: float = 60.0  # seconds per upstream HTTP request
    faults: list[Fault] = field(default_factory=list)

    @property
    def target(self) -> str:
        return self.command or self.url or ""


def load(path: str) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    server = raw.get("server") or {}
    command = server.get("command")
    url = server.get("url")
    if bool(command) == bool(url):
        raise ValueError("config: exactly one of `server.command` (stdio) or "
                         "`server.url` (Streamable HTTP) is required")

    faults = []
    for i, item in enumerate(raw.get("faults") or []):
        ftype = item.get("type")
        if ftype not in FAULT_TYPES:
            raise ValueError(
                f"config: faults[{i}].type '{ftype}' invalid; "
                f"expected one of {sorted(FAULT_TYPES)}"
            )
        if not item.get("tool"):
            raise ValueError(f"config: faults[{i}].tool is required")
        faults.append(
            Fault(
                tool=item["tool"],
                type=ftype,
                after_calls=int(item.get("after_calls", 1)),
                probability=float(item.get("probability", 1.0)),
                payload=item.get("payload"),
                delay_ms=int(item.get("delay_ms", 2000)),
            )
        )

    return Config(command=command, url=url,
                  headers=server.get("headers") or {},
                  http_timeout=float(server.get("http_timeout", 60)),
                  faults=faults)
