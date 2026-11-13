"""Thread-safe, process-local event history."""

import json
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Callable

from pydantic import BaseModel, Field


class JobEvent(BaseModel):
    seq: int = Field(ge=1)
    ts: datetime
    type: str
    data: dict


class EventLog:
    """Keep independent sequences per job; callers receive detached snapshots."""

    def __init__(self, clock: Callable[[], datetime] | None = None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._events: dict[str, list[JobEvent]] = defaultdict(list)
        self._lock = Lock()

    def append(self, job_id: str, type: str, data: dict, *, ts: datetime | None = None) -> JobEvent:
        with self._lock:
            events = self._events[job_id]
            event = JobEvent(seq=len(events) + 1, ts=ts if ts is not None else self._clock(),
                             type=type, data=deepcopy(data))
            events.append(event)
            return deepcopy(event)

    def read_since(self, job_id: str, last_seq: int) -> list[JobEvent]:
        with self._lock:
            return deepcopy([event for event in self._events.get(job_id, ()) if event.seq > last_seq])


def format_sse(event: JobEvent) -> str:
    """Encode the event payload as one JSON data line without blocking."""
    if "\n" in event.type or "\r" in event.type:
        raise ValueError("SSE event types cannot contain line breaks")
    payload = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.seq}\nevent: {event.type}\ndata: {payload}\n\n"
