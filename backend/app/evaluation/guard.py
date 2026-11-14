"""Bound engine.run calls in a serial, killable worker process.

Registry engines must be pickleable and perform one inference per run call.
Nested provider calls are outside this accounting contract.
"""

from __future__ import annotations

import math
from contextlib import redirect_stdout
import os
import pickle
from queue import Empty, Queue
import subprocess
import sys
from threading import Lock, Thread
from time import monotonic


class ResourceGuardError(RuntimeError):
    """An experiment authorization or resource limit was violated."""


class RealEngineRefused(ResourceGuardError):
    pass


class InferenceLimitReached(ResourceGuardError):
    pass


class RunTimeout(ResourceGuardError):
    pass


def _worker():
    """Private binary protocol over inherited anonymous standard-I/O pipes."""
    source, sink = sys.stdin.buffer, sys.stdout.buffer
    try:
        while True:
            engine, args = pickle.load(source)
            events = []
            try:
                with redirect_stdout(sys.stderr):
                    findings = engine.run(*args, lambda *event: events.append(event))
                response = (True, findings, events)
            except Exception as exc:
                response = (False, type(exc).__name__, str(exc))
            pickle.dump(response, sink)
            sink.flush()
    except EOFError:
        pass


def _read_responses(stream, responses):
    try:
        while True:
            responses.put(pickle.load(stream))
    except (EOFError, OSError) as exc:
        responses.put(exc)


class ResourceGuard:
    max_concurrent_inferences = 1

    def __init__(self, max_inferences=1000, per_run_timeout=30.0, *, real=False):
        if type(max_inferences) is not int or max_inferences < 0:
            raise ValueError("max_inferences must be a nonnegative integer")
        if isinstance(per_run_timeout, bool) or not math.isfinite(per_run_timeout) or per_run_timeout <= 0:
            raise ValueError("per_run_timeout must be finite and positive")
        self.max_inferences = max_inferences
        self.per_run_timeout = per_run_timeout
        self.real = real
        self.inferences = 0
        self._lock = Lock()
        self._process = None
        self._responses = Queue()

    def authorize(self, *, is_fake):
        if not is_fake and not (self.real and os.getenv("REVIEW_EXPERIMENT_ALLOW_REAL") == "1"):
            raise RealEngineRefused("Non-fake engines require --real AND REVIEW_EXPERIMENT_ALLOW_REAL=1")

    def wrap(self, engine, *, is_fake):
        self.authorize(is_fake=is_fake)
        guard = self

        class GuardedEngine:
            def run(self, case, requirements, budget, emit):
                return guard._run(engine, (case, requirements, budget), emit, is_fake)

        return GuardedEngine()

    def _stop(self):
        if self._process is not None:
            self._process.kill()
            self._process.wait()
            self._reader.join()
            self._process.stdin.close()
            self._process.stdout.close()
            self._process = None
            self._responses = Queue()

    def _run(self, engine, args, emit, is_fake):
        self.authorize(is_fake=is_fake)
        deadline = monotonic() + self.per_run_timeout
        if not self._lock.acquire(timeout=self.per_run_timeout):
            raise RunTimeout("Timed out waiting for the single inference slot")
        try:
            if self.inferences >= self.max_inferences:
                raise InferenceLimitReached("max_inferences exhausted")
            if monotonic() >= deadline:
                raise RunTimeout("Run deadline exhausted")
            if self._process is None:
                bootstrap = f"import sys; sys.path[:] = {sys.path!r}; from app.evaluation.guard import _worker; _worker()"
                self._process = subprocess.Popen([sys.executable, "-u", "-c", bootstrap],
                                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                 stderr=subprocess.DEVNULL)
                self._reader = Thread(target=_read_responses,
                                      args=(self._process.stdout, self._responses), daemon=True)
                self._reader.start()
            self.inferences += 1
            try:
                pickle.dump((engine, args), self._process.stdin)
                self._process.stdin.flush()
                try:
                    response = self._responses.get(timeout=max(0, deadline - monotonic()))
                except Empty:
                    raise RunTimeout("Engine run exceeded per-run timeout; worker terminated")
                if isinstance(response, Exception):
                    raise response
                ok, result, events = response
            except (RunTimeout, EOFError, BrokenPipeError):
                self._stop()
                raise
            if not ok:
                raise RuntimeError(f"Engine failed: {result}: {events}")
            for event in events:
                emit(*event)
            return result
        finally:
            self._lock.release()

    def close(self):
        with self._lock:
            self._stop()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
