import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Event

import pytest

from app.jobs import EventLog, JobEvent, JobRunner, JobState, format_sse


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def jobs(sf1_fake_provider_env):
    runners, gates = [], []

    def make(work_fn, **kwargs):
        ids = iter(f"job-{n}" for n in range(20))
        log = EventLog(clock=lambda: NOW)
        runner = JobRunner(work_fn, log, lambda: NOW, lambda: next(ids), **kwargs)
        runners.append(runner)
        return runner, log

    def gate():
        event = Event()
        gates.append(event)
        return event

    yield make, gate
    for event in gates:
        event.set()
    for runner in runners:
        runner.shutdown()


def test_log_sequences_replay_and_snapshot_isolation(sf1_fake_provider_env):
    log = EventLog(lambda: NOW)
    payload = {"nested": {"value": 1}}
    first = log.append("a", "progress", payload)
    payload["nested"]["value"] = 99
    first.data["nested"]["value"] = 88
    log.append("a", "progress", {"step": 2})
    assert log.append("b", "progress", {}).seq == 1
    assert [event.seq for event in log.read_since("a", 0)] == [1, 2]
    assert [event.seq for event in log.read_since("a", 1)] == [2]
    snapshot = log.read_since("a", 0)
    assert snapshot[0].data == {"nested": {"value": 1}}
    assert snapshot[0].ts == NOW
    snapshot[0].seq = 100
    assert log.read_since("a", 0)[0].seq == 1
    assert log.read_since("a", 2) == []
    assert log.read_since("missing", 0) == []


def test_log_concurrent_appends_are_ordered(sf1_fake_provider_env):
    log = EventLog(lambda: NOW)
    barrier = Barrier(4)

    def append_batch(worker):
        barrier.wait(timeout=5)
        for index in range(25):
            log.append("shared", "progress", {"worker": worker, "index": index})

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(append_batch, worker) for worker in range(4)]
        for future in futures:
            future.result(timeout=5)
    events = log.read_since("shared", 0)
    assert [event.seq for event in events] == list(range(1, 101))
    assert {(event.data["worker"], event.data["index"]) for event in events} == {
        (worker, index) for worker in range(4) for index in range(25)
    }


def test_sse_formatting(sf1_fake_provider_env):
    event = JobEvent(seq=3, ts=NOW, type="progress", data={"text": "line\nnext", "value": "Việt"})
    wire = format_sse(event)
    assert wire.startswith("id: 3\nevent: progress\ndata: ")
    assert wire.endswith("\n\n")
    assert len(wire.splitlines()) == 4
    assert json.loads(wire.splitlines()[2][6:]) == event.data
    assert format_sse(JobEvent(seq=1, ts=NOW, type="job.done", data={})) == (
        "id: 1\nevent: job.done\ndata: {}\n\n"
    )


@pytest.mark.parametrize("event_type", ["bad\nevent", "bad\revent"])
def test_sse_rejects_event_line_injection(event_type, sf1_fake_provider_env):
    with pytest.raises(ValueError):
        format_sse(JobEvent(seq=1, ts=NOW, type=event_type, data={}))


def test_success_and_resume_replay(jobs):
    make, _ = jobs
    seen = []

    def work(job_id, job_input, emit, is_cancelled):
        seen.append((job_id, job_input, is_cancelled()))
        emit("progress", {"step": 1})
        emit("progress", {"step": 2})

    runner, log = make(work)
    job_id = runner.submit({"query": "test"})
    assert runner.wait(job_id, 5) == JobState.SUCCEEDED
    assert runner.status(job_id) == "SUCCEEDED"
    assert seen == [(job_id, {"query": "test"}, False)]
    assert [event.type for event in log.read_since(job_id, 0)] == [
        "job.started", "progress", "progress", "job.done"
    ]
    assert all(event.ts == NOW for event in log.read_since(job_id, 0))

    async def collect(last_seq):
        return [event async for event in runner.iter_events(job_id, last_seq, poll_interval=0)]

    replay = asyncio.run(asyncio.wait_for(collect(1), timeout=5))
    assert [event.seq for event in replay] == [2, 3, 4]
    assert asyncio.run(asyncio.wait_for(collect(4), timeout=5)) == []
    runner.cancel(job_id)
    assert runner.status(job_id) == JobState.SUCCEEDED
    assert len(log.read_since(job_id, 0)) == 4


def test_failure_has_message_only(jobs):
    make, _ = jobs

    def work(job_id, job_input, emit, is_cancelled):
        raise ValueError("work failed")

    runner, log = make(work)
    job_id = runner.submit(None)
    assert runner.wait(job_id, 5) == JobState.FAILED
    events = log.read_since(job_id, 0)
    assert [event.type for event in events] == ["job.started", "job.failed"]
    assert events[-1].data == {"message": "work failed"}
    assert "Traceback" not in format_sse(events[-1])


def test_default_single_worker_queues_second_job(jobs):
    make, gate = jobs
    started, release, second_started = gate(), gate(), gate()
    order = []

    def work(job_id, job_input, emit, is_cancelled):
        order.append(job_input)
        if job_input == "first":
            started.set()
            assert release.wait(5)
        else:
            second_started.set()

    runner, log = make(work)
    first = runner.submit("first")
    assert started.wait(5)
    second = runner.submit("second")
    assert runner.status(first) == JobState.RUNNING
    assert runner.status(second) == JobState.QUEUED
    assert not second_started.is_set()
    assert log.read_since(second, 0) == []
    release.set()
    assert runner.wait(first, 5) == JobState.SUCCEEDED
    assert runner.wait(second, 5) == JobState.SUCCEEDED
    assert second_started.is_set()
    assert order == ["first", "second"]


def test_queued_cancellation_is_immediate_and_never_runs(jobs):
    make, gate = jobs
    started, release = gate(), gate()
    inputs = []

    def work(job_id, job_input, emit, is_cancelled):
        inputs.append(job_input)
        started.set()
        assert release.wait(5)

    runner, log = make(work, max_concurrent=1)
    first = runner.submit("first")
    assert started.wait(5)
    cancelled = runner.submit("cancelled")
    runner.cancel(cancelled)
    runner.cancel(cancelled)
    assert runner.wait(cancelled, 0) == JobState.CANCELLED
    assert [(event.seq, event.type) for event in log.read_since(cancelled, 0)] == [
        (1, "job.cancelled")
    ]
    release.set()
    assert runner.wait(first, 5) == JobState.SUCCEEDED
    runner.shutdown()
    assert inputs == ["first"]


def test_running_cancellation_flag_is_observed(jobs):
    make, gate = jobs
    started, inspect_cancel = gate(), gate()
    observed = []

    def work(job_id, job_input, emit, is_cancelled):
        started.set()
        assert inspect_cancel.wait(5)
        observed.append(is_cancelled())
        emit("progress", {"cancel_seen": is_cancelled()})

    runner, log = make(work)
    job_id = runner.submit(None)
    assert started.wait(5)
    runner.cancel(job_id)
    assert runner.status(job_id) == JobState.RUNNING
    inspect_cancel.set()
    assert runner.wait(job_id, 5) == JobState.CANCELLED
    assert observed == [True]
    assert [event.type for event in log.read_since(job_id, 0)] == [
        "job.started", "progress", "job.cancelled"
    ]


def test_progress_is_streamed_before_job_finishes(jobs):
    make, gate = jobs
    progress_ready, release = gate(), gate()

    def work(job_id, job_input, emit, is_cancelled):
        emit("progress", {"step": 1})
        progress_ready.set()
        assert release.wait(5)
        emit("progress", {"step": 2})

    runner, _ = make(work)
    job_id = runner.submit(None)
    assert progress_ready.wait(5)

    async def stream():
        events = runner.iter_events(job_id, poll_interval=0)
        assert (await anext(events)).type == "job.started"
        event = await anext(events)
        assert event.type == "progress" and event.seq == 2
        assert runner.status(job_id) == JobState.RUNNING
        # With no pending events the poll must yield control to the event loop.
        asyncio.get_running_loop().call_soon(release.set)
        remaining = [event async for event in events]
        assert [(event.seq, event.type) for event in remaining] == [
            (3, "progress"), (4, "job.done")
        ]

    asyncio.run(asyncio.wait_for(stream(), timeout=5))
    assert runner.wait(job_id, 5) == JobState.SUCCEEDED


def test_stream_can_remain_open_after_terminal(jobs):
    make, _ = jobs
    runner, log = make(lambda *args: None)
    job_id = runner.submit(None)
    assert runner.wait(job_id, 5) == JobState.SUCCEEDED

    async def stream():
        events = runner.iter_events(job_id, last_seq=2, poll_interval=0, stop_when_terminal=False)
        asyncio.get_running_loop().call_soon(log.append, job_id, "extra", {})
        assert (await anext(events)).seq == 3
        await events.aclose()

    asyncio.run(asyncio.wait_for(stream(), timeout=5))


def test_wait_timeout_and_unknown_job(jobs):
    make, gate = jobs
    release = gate()

    def work(*args):
        assert release.wait(5)

    runner, _ = make(work)
    job_id = runner.submit(None)
    with pytest.raises(TimeoutError):
        runner.wait(job_id, 0)
    for operation in (runner.status, runner.cancel, runner.wait):
        with pytest.raises(KeyError):
            operation("unknown")
    release.set()
    assert runner.wait(job_id, 5) == JobState.SUCCEEDED


def test_explicit_concurrency_allows_two_workers(jobs):
    make, gate = jobs
    started = [gate(), gate()]
    release = gate()

    def work(job_id, job_input, emit, is_cancelled):
        started[job_input].set()
        assert release.wait(5)

    runner, _ = make(work, max_concurrent=2)
    ids = [runner.submit(index) for index in range(2)]
    assert all(event.wait(5) for event in started)
    assert all(runner.status(job_id) == JobState.RUNNING for job_id in ids)
    release.set()
    assert all(runner.wait(job_id, 5) == JobState.SUCCEEDED for job_id in ids)
