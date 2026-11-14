"""Stable error payloads at review API boundaries."""

from datetime import datetime, timezone

from test_review_api import api, ready, run
from app.review.service import ReviewCaseService
from app.review.schemas import Requirement, ReviewCase
from app.review_adapters import PipelineReviewEngine


def test_missing_finding_and_case_codes(api):
    client, _, _ = api
    assert client.put("/api/review/findings/missing/decision", json={"review": "ACCEPT"}).json() == {
        "code": "FINDING_NOT_FOUND", "message": "Finding not found",
    }
    assert client.get("/api/review/cases/missing").json() == {
        "code": "CASE_NOT_FOUND", "message": "Case not found",
    }


def test_invalid_decision_message_is_stable(api):
    client, runtime, _ = api
    case_id = ready(client)
    run(client, runtime, case_id)
    finding = client.get(f"/api/review/cases/{case_id}").json()["findings"][0]
    response = client.put(f"/api/review/findings/{finding['id']}/decision", json={"review": "EDIT"})
    assert response.status_code == 422
    assert response.json() == {"code": "VALIDATION_ERROR", "message": "Edited text is required for this decision"}


def test_unexpected_service_error_is_sanitized(api, monkeypatch):
    client, runtime, _ = api
    case_id = ready(client)
    run(client, runtime, case_id)

    def fail(*args, **kwargs):
        raise RuntimeError("boom-internal")

    monkeypatch.setattr(ReviewCaseService, "decide_finding", fail)
    finding = client.get(f"/api/review/cases/{case_id}").json()["findings"][0]
    response = client.put(f"/api/review/findings/{finding['id']}/decision", json={"review": "ACCEPT"})
    assert response.status_code == 500
    assert response.json() == {"code": "INTERNAL_ERROR", "message": "Internal error"}
    assert "boom-internal" not in response.text


def test_task_failed_payload_hides_exception_and_logs_it(caplog):
    class BrokenPipeline:
        async def run(self, *args, **kwargs):
            raise ValueError("secret-internal-string")

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    case = ReviewCase(id="case", owner_user_id="owner", title="Review", request_text="Check",
                      created_at=now, updated_at=now)
    requirement = Requirement(id="requirement", case_id="case", text="Check", confirmed=True,
                              origin="USER", order=0)
    events = []
    result = PipelineReviewEngine(BrokenPipeline()).run(case, [requirement], None,
                                                        lambda name, payload: events.append((name, payload)))
    failed = next(payload for name, payload in events if name == "task.failed")
    serialized = str(failed)
    assert failed["error_type"] == "UNKNOWN"
    assert "secret-internal-string" not in serialized and "ValueError" not in serialized
    assert "secret-internal-string" in caplog.text
    assert len(result) == 1

