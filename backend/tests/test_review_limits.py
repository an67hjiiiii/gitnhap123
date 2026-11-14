from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.ratelimit import SlidingWindowRateLimiter
from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.review.engine import FakeReviewEngine


def test_sliding_window_limits_isolation_retry_and_disable():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])
    assert limiter.allow("alice", "runs", 1) == (True, 0)
    assert limiter.allow("alice", "runs", 1) == (False, 60)
    assert limiter.allow("bob", "runs", 1) == (True, 0)
    assert limiter.allow("alice", "reads", 1) == (True, 0)
    assert limiter.allow("alice", "runs", 0) == (True, 0)
    now[0] = 30
    assert limiter.allow("alice", "runs", 1) == (False, 30)
    now[0] = 60
    assert limiter.allow("alice", "runs", 1) == (True, 0)


def test_request_limits_and_effective_run_budget(monkeypatch):
    monkeypatch.setenv("REVIEW_RATE_RUNS_PER_MIN", "0")
    monkeypatch.setenv("REVIEW_RATE_READS_PER_MIN", "0")
    monkeypatch.setenv("REVIEW_MAX_REQUEST_CHARS", "4")
    monkeypatch.setenv("REVIEW_MAX_REQUIREMENT_CHARS", "4")
    monkeypatch.setenv("REVIEW_MAX_REQUIREMENTS_PER_CASE", "1")
    monkeypatch.setenv("REVIEW_MAX_REQUIREMENTS", "3")
    monkeypatch.setenv("REVIEW_MAX_SECONDS", "10")
    runtime = ReviewRuntime()
    app = FastAPI()

    def user(request: Request):
        return {"user_id": "alice"}

    app.include_router(build_router(current_user=user, runtime=runtime))
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine()
    with TestClient(app) as client:
        at_limit = client.post("/api/review/cases", json={"title": "A", "request_text": "1234"})
        assert at_limit.status_code == 201
        assert client.post("/api/review/cases", json={"title": "A", "request_text": "12345"}).json()["code"] == "VALIDATION_ERROR"
        case_id = at_limit.json()["id"]
        assert client.put(f"/api/review/cases/{case_id}/requirements", json={"requirements": [
            {"text": "1234", "confirmed": True}
        ]}).status_code == 200
        response = client.put(f"/api/review/cases/{case_id}/requirements", json={"requirements": [
            {"text": "a", "confirmed": True}, {"text": "b", "confirmed": True}
        ]})
        assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"
        response = client.post(f"/api/review/cases/{case_id}/runs", json={"budget": {
            "max_requirements": 1000000, "max_seconds": 1000000
        }})
        assert response.status_code == 202, response.text
        assert response.json()["budget"] == {"max_requirements": 3, "max_seconds": 10}
        job_id = response.json()["id"]
        runtime.runner.wait(job_id, timeout=5)
        lower = client.post(f"/api/review/cases/{case_id}/runs", json={"budget": {"max_requirements": 2}})
        assert lower.status_code in (202, 409)
    runtime.runner.shutdown()


def test_read_and_run_rate_limits_are_separate(monkeypatch):
    monkeypatch.setenv("REVIEW_RATE_RUNS_PER_MIN", "1")
    monkeypatch.setenv("REVIEW_RATE_READS_PER_MIN", "1")
    runtime = ReviewRuntime()
    app = FastAPI()

    def user(request: Request):
        return {"user_id": request.headers.get("x-user", "alice")}

    app.include_router(build_router(current_user=user, runtime=runtime))
    with TestClient(app) as client:
        assert client.get("/api/review/cases").status_code == 200
        limited = client.get("/api/review/cases")
        assert limited.status_code == 429
        assert limited.json() == {"code": "RATE_LIMITED", "message": "Too many requests"}
        assert limited.headers["retry-after"] >= "1"
        assert client.get("/api/review/cases", headers={"x-user": "bob"}).status_code == 200
    runtime.runner.shutdown()
