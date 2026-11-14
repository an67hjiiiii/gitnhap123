from __future__ import annotations

import time

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.review.engine import FakeReviewEngine


@pytest.fixture
def api(monkeypatch, sf1_vector_store):
    monkeypatch.setenv("PROVIDER", "fake")
    runtime = ReviewRuntime()
    app = FastAPI()

    def current_user(request: Request):
        user = request.headers.get("x-user", "alice")
        if user == "anonymous":
            raise HTTPException(401, "Authentication is required")
        return {"user_id": user, "role": "USER"}

    app.include_router(build_router(current_user=current_user, runtime=runtime))
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine()
    with TestClient(app) as client:
        yield client, runtime, app
    runtime.runner.shutdown()


def ready(client):
    response = client.post("/api/review/cases", json={
        "title": "Audit", "source_ids": ["source-1"], "request_text": "Check policy. Check approval.",
    })
    assert response.status_code == 201
    case_id = response.json()["id"]
    proposal = client.post(f"/api/review/cases/{case_id}/requirements:propose")
    assert proposal.status_code == 200
    requirements = [{"id": r["id"], "text": r["text"], "confirmed": True} for r in proposal.json()]
    assert client.put(f"/api/review/cases/{case_id}/requirements",
                      json={"requirements": requirements}).status_code == 200
    return case_id


def test_run_sse_first_event_latency_sequence_and_resume(api):
    client, runtime, app = api
    case_id = ready(client)
    started = time.perf_counter()
    response = client.post(f"/api/review/cases/{case_id}/runs", json={"budget": {"tasks": 2}})
    posted_at = time.perf_counter()
    assert response.status_code == 202
    job_id = response.json()["id"]
    streamed = client.get(f"/api/review/runs/{job_id}/events")
    first_event_at = time.perf_counter()
    assert first_event_at - posted_at < 2.0
    assert first_event_at - started < 2.0
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    blocks = streamed.text.strip().split("\n\n")
    seqs = [int(block.splitlines()[0].removeprefix("id: ")) for block in blocks]
    assert seqs == list(range(1, len(seqs) + 1))
    replay = client.get(f"/api/review/runs/{job_id}/events", headers={"Last-Event-ID": "2"})
    assert replay.text == "\n\n".join(blocks[2:]) + "\n\n"
