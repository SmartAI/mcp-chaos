"""Record proxy events to a JSONL run file for later reporting."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Event:
    t: float  # seconds since session start
    kind: str  # "tool_call" | "fault" | "response" | "session_start"
    tool: str | None = None
    detail: dict = field(default_factory=dict)


class Recorder:
    """Appends each event to the run file as it happens.

    Real MCP clients terminate the proxy with a signal at session end, so
    buffering events until shutdown would lose the whole run. The file is
    opened in append mode because some clients restart the MCP server
    mid-session, relaunching the proxy — truncating would wipe everything
    recorded so far. Each launch writes a `session_start` marker instead.
    """

    def __init__(self, path: str, **session_detail):
        self._file = open(path, "a")
        self._start = time.monotonic()
        self._events: list[Event] = []
        self.log("session_start",
                 started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 **session_detail)

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
