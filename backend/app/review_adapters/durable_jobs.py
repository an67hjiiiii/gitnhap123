"""Leased database workers with checkpointed findings and replayable SSE events."""

import asyncio
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from app.jobs.events import JobEvent
from app.review.schemas import JobState
from app.review.service import RunCancelled


_TERMINAL = {JobState.SUCCEEDED, JobState.PARTIAL, JobState.FAILED, JobState.CANCELLED}


def _positive_env(name, default):
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


class DurableJobRunner:
    def __init__(self, queue, work_fn, lease_owner, lease_seconds, clock, max_concurrent=1):
        if not lease_owner or lease_seconds <= 0 or max_concurrent < 1:
            raise ValueError("A lease owner, positive lease and worker count are required")
        self.queue, self.work_fn = queue, work_fn
        self.lease_owner, self.lease_seconds, self.clock = lease_owner, lease_seconds, clock
        # The HTTP runtime supplies the historical 30-second lease positionally.
        self.lease_seconds = _positive_env("REVIEW_LEASE_SECONDS", lease_seconds)
        self.heartbeat_seconds = _positive_env("REVIEW_HEARTBEAT_SECONDS", self.lease_seconds / 3)
        if self.heartbeat_seconds >= self.lease_seconds:
            self.heartbeat_seconds = self.lease_seconds / 3
        self.recover_interval_seconds = _positive_env("REVIEW_RECOVER_INTERVAL_SECONDS", 5)
        self.max_concurrent = max_concurrent
        self._stop, self._wake, self._changed = Event(), Event(), Event()
        self._lock = Lock()
        self._executor = None
        self._futures = []
        self._inputs = {}
        self._recovery_thread = None

    def start_recovery(self):
        """Run periodic expired-lease recovery until this runner shuts down."""
        with self._lock:
            if self._recovery_thread is None and not self._stop.is_set():
                self._recovery_thread = Thread(
                    target=self._recover_periodically, daemon=True, name="review-recovery",
                )
                self._recovery_thread.start()

    def _recover_periodically(self):
        while not self._stop.wait(self.recover_interval_seconds):
            try:
                self.recover(self.clock())
            except Exception:
                logging.getLogger(__name__).exception("Periodic review recovery failed")

    def start(self):
        with self._lock:
            if self._executor is None and not self._stop.is_set():
                self._executor = ThreadPoolExecutor(max_workers=self.max_concurrent,
                                                    thread_name_prefix="review-worker")
                self._futures = [self._executor.submit(self._worker)
                                 for _ in range(self.max_concurrent)]
        self._wake.set()

    def submit(self, job_input):
        job_id = str(uuid4())
        with self._lock:
            self._inputs[job_id] = dict(job_input)
            try:
                self.queue.enqueue_job(job_input["owner"], job_input["case_id"], job_id,
                                       job_input.get("budget"))
            except BaseException:
                self._inputs.pop(job_id, None)
                raise
        # Local dependency overrides are retained; another process rebuilds the configured engine.
        self.start()
        return job_id

    def recover(self, now):
        recovered = self.queue.recover_jobs(now)
        self._wake.set()
        self._changed.set()
        return recovered

    def _worker(self):
        while not self._stop.is_set():
            self._wake.clear()
            try:
                row = self.queue.claim_next_job(
                    self.lease_owner, self.lease_seconds, self.clock(),
                    all_owners=True, prepare_case=True,
                )
                if row is not None:
                    self._run(row)
                    continue
            except Exception:
                # Database outages leave leases recoverable. Retry without spinning.
                pass
            self._wake.wait(0.05)

    def _run(self, row):
        job_id, owner = row["id"], row["owner_user_id"]
        with self._lock:
            local_input = self._inputs.pop(job_id, {})
        heartbeat_stop, lost_lease = Event(), Event()

        def heartbeat():
            while not heartbeat_stop.wait(self.heartbeat_seconds):
                try:
                    valid = self.queue.heartbeat(job_id, self.lease_owner,
                                                 self.lease_seconds, self.clock(),
                                                 owner_user_id=owner)
                except Exception:
                    valid = False
                if not valid:
                    lost_lease.set()
                    return

        def cancelled():
            current = self.queue.job_record(job_id)
            return (lost_lease.is_set() or current["state"] != "RUNNING"
                    or current["lease_owner"] != self.lease_owner
                    or current["lease_expires_at"] <= self.clock())

        def emit(type, data):
            if cancelled():
                raise RunCancelled()
            event = self.queue.append_event(job_id, type, data, self.clock(),
                                            owner_user_id=owner, lease_owner=self.lease_owner)
            if event is None:
                raise RunCancelled()
            self._changed.set()
            return JobEvent.model_validate(event)

        thread = Thread(target=heartbeat, daemon=True, name="review-heartbeat")
        thread.start()
        try:
            emit("job.started", {})
            if row["attempt"] > 1:
                emit("job.resumed", {"attempt": row["attempt"]})
            result = self.work_fn(job_id, {
                **local_input, "owner": owner, "case_id": row["case_id"], "budget": row["budget"],
                "attempt": row["attempt"],
            }, emit, cancelled)
            state = JobState.PARTIAL if result == JobState.PARTIAL else JobState.SUCCEEDED
            if not cancelled():
                self.queue.finish_job(job_id, self.lease_owner, state, self.clock(),
                                      owner_user_id=owner, event_type="job.done", update_case=True)
        except RunCancelled:
            pass
        except Exception as exc:
            self.queue.finish_job(job_id, self.lease_owner, JobState.FAILED, self.clock(),
                                  str(exc), owner_user_id=owner,
                                  event_type="job.failed", update_case=True)
        finally:
            # BaseException deliberately leaves RUNNING intact, simulating process death.
            heartbeat_stop.set()
            thread.join()
            self._changed.set()

    def checkpoint(self, job_id, finding):
        row = self.queue.job_record(job_id)
        if not self.queue.checkpoint_finding(job_id, self.lease_owner, self.clock(), finding,
                                              owner_user_id=row["owner_user_id"]):
            raise RunCancelled()
        self._changed.set()

    def cancel(self, job_id):
        row = self.queue.job_record(job_id)
        self.queue.cancel_job(job_id, self.clock(), owner_user_id=row["owner_user_id"])
        with self._lock:
            self._inputs.pop(job_id, None)
        self._changed.set()

    def status(self, job_id):
        return JobState(self.queue.job_record(job_id)["state"])

    def read_since(self, job_id, last_seq):
        row = self.queue.job_record(job_id)
        return [JobEvent.model_validate(value) for value in self.queue.read_events(
            job_id, last_seq, owner_user_id=row["owner_user_id"],
        )]

    def wait(self, job_id, timeout=None):
        deadline = None if timeout is None else monotonic() + timeout
        while True:
            self._changed.clear()
            state = self.status(job_id)
            if state in _TERMINAL:
                return state
            remaining = None if deadline is None else deadline - monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError(job_id)
            self._changed.wait(0.05 if remaining is None else min(remaining, 0.05))

    async def iter_events(self, job_id, last_seq=0, poll_interval=0.05, stop_when_terminal=True):
        if poll_interval < 0:
            raise ValueError("poll_interval must be nonnegative")
        while True:
            terminal = self.status(job_id) in _TERMINAL
            for event in self.read_since(job_id, last_seq):
                last_seq = event.seq
                yield event
            if stop_when_terminal and terminal:
                return
            await asyncio.sleep(poll_interval)

    def shutdown(self, wait=True):
        self._stop.set()
        self._wake.set()
        if self._recovery_thread is not None:
            self._recovery_thread.join()
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
