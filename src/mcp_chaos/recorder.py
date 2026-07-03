"""Record proxy events to a JSONL run file for later reporting."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field


@dataclass
class Event:
    t: float  # seconds since run start
    kind: str  # "tool_call" | "fault" | "response"
    tool: str | None = None
    detail: dict = field(default_factory=dict)


class Recorder:
    """Appends each event to the run file as it happens.

    Real MCP clients terminate the proxy with a signal at session end, so
    buffering events until shutdown would lose the whole run.
    """

    def __init__(self, path: str):
        self._start = time.monotonic()
        self._events: list[Event] = []
        self._file = open(path, "w")

    def log(self, kind: str, tool: str | None = None, **detail) -> None:
        event = Event(t=round(time.monotonic() - self._start, 3), kind=kind,
                      tool=tool, detail=detail)
        self._events.append(event)
        self._file.write(json.dumps(asdict(event)) + "\n")
        self._file.flush()

    @property
    def events(self) -> list[Event]:
        return self._events

    def flush(self) -> None:
        self._file.flush()
