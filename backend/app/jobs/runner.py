"""An executor-backed job runner with cooperative cancellation."""

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Event, RLock
from typing import AsyncIterator, Callable

from .events import EventLog, JobEvent


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_TERMINAL = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}


@dataclass
class _Job:
    state: JobState = JobState.QUEUED
    cancelled: Event = field(default_factory=Event)
    done: Event = field(default_factory=Event)
    future: Future | None = None


class JobRunner:
    def __init__(self, work_fn: Callable, event_log: EventLog,
                 clock: Callable[[], datetime], id_factory: Callable[[], str],
                 max_concurrent: int = 1):
        self._work_fn = work_fn
        self._event_log = event_log
        self._clock = clock
        self._id_factory = id_factory
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._jobs: dict[str, _Job] = {}
        self._lock = RLock()

    def submit(self, job_input) -> str:
        with self._lock:
            job_id = self._id_factory()
            if job_id in self._jobs:
                raise ValueError(f"Duplicate job ID: {job_id}")
            job = _Job()
            self._jobs[job_id] = job
            try:
                job.future = self._executor.submit(self._run, job_id, job_input)
            except Exception:
                del self._jobs[job_id]
                raise
            return job_id

    def _emit(self, job_id: str, type: str, data: dict) -> JobEvent:
        return self._event_log.append(job_id, type, data, ts=self._clock())

    def _finish(self, job_id: str, state: JobState, type: str, data: dict) -> None:
        # Called with the runner lock: terminal status always implies a final event.
        self._emit(job_id, type, data)
        job = self._jobs[job_id]
        job.state = state
        job.done.set()

    def _run(self, job_id: str, job_input) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.state == JobState.CANCELLED:
                return
            job.state = JobState.RUNNING
            self._emit(job_id, "job.started", {})
        try:
            self._work_fn(job_id, job_input,
                          lambda type, data: self._emit(job_id, type, data),
                          job.cancelled.is_set)
        except Exception as exc:
            with self._lock:
                self._finish(job_id, JobState.FAILED, "job.failed", {"message": str(exc)})
        else:
            with self._lock:
                if job.cancelled.is_set():
                    self._finish(job_id, JobState.CANCELLED, "job.cancelled", {})
                else:
                    self._finish(job_id, JobState.SUCCEEDED, "job.done", {})

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.state in _TERMINAL:
                return
            job.cancelled.set()
            if job.state == JobState.QUEUED:
                if job.future is not None:
                    job.future.cancel()
                self._finish(job_id, JobState.CANCELLED, "job.cancelled", {})

    def status(self, job_id: str) -> JobState:
        with self._lock:
            return self._jobs[job_id].state

    def wait(self, job_id: str, timeout: float | None = None) -> JobState:
        with self._lock:
            done = self._jobs[job_id].done
        if not done.wait(timeout):
            raise TimeoutError(f"Job {job_id} did not finish within the timeout")
        return self.status(job_id)

    async def iter_events(self, job_id: str, last_seq: int = 0,
                          poll_interval: float = 0.05,
                          stop_when_terminal: bool = True) -> AsyncIterator[JobEvent]:
        """Replay then poll; snapshot status first to avoid losing the final event."""
        if poll_interval < 0:
            raise ValueError("poll_interval must be nonnegative")
        while True:
            terminal = self.status(job_id) in _TERMINAL
            for event in self._event_log.read_since(job_id, last_seq):
                last_seq = event.seq
                yield event
            if stop_when_terminal and terminal:
                return
            await asyncio.sleep(poll_interval)

    def shutdown(self, wait: bool = True) -> None:
        """Release executor resources; running work must cooperate to finish."""
        self._executor.shutdown(wait=wait)
