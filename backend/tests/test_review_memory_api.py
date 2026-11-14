from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.review import ReviewRuntime, build_router
from app.review.memory import InMemoryMemoryStore
from app.review.schemas import Decision, Finding, Requirement, RequirementOrigin, Verdict


def _api(memory_store):
    runtime = ReviewRuntime(memory_store=memory_store)
    app = FastAPI()

    def current_user(request: Request):
        token = request.headers.get("authorization", "")
        if token not in {"Bearer alice", "Bearer bob"}:
            raise HTTPException(401, "Authentication is required")
        return {"user_id": token.removeprefix("Bearer "), "role": "USER"}

    app.include_router(build_router(current_user=current_user, runtime=runtime))
    return TestClient(app), runtime


def _seed(runtime, owner, source_id, requirement_id, *, text="Password length must be twelve characters"):
    service = runtime.service(None)
    case = service.create_case(owner, "Review", "Review policy", [source_id])
    requirement = Requirement(
        id=requirement_id, case_id=case.id, text=text,
        origin=RequirementOrigin.USER, confirmed=False, order=0,
    )
    runtime.repository.save_requirements(owner, case.id, [requirement])
    finding = Finding(
        id=f"finding-{requirement_id}", case_id=case.id,
        requirement_id=requirement_id, verdict=Verdict.SATISFIED, confidence="L1",
    )
    runtime.repository.save_findings(owner, case.id, [finding])
    return case, requirement, finding


def test_decisions_are_recorded_and_similar_requirements_receive_suggestions():
    memory = InMemoryMemoryStore(id_factory=lambda: "memory-entry")
    client, runtime = _api(memory)
    try:
        source = "shared-project-source"
        first, _, finding = _seed(runtime, "alice", source, "req-1")
        second, _, _ = _seed(runtime, "alice", source, "req-2")

        before = client.get(
            f"/api/review/cases/{second.id}/requirements/req-2/suggestions",
            headers={"Authorization": "Bearer alice"},
        )
        assert before.status_code == 200 and before.json() == []
        assert memory.list_entries("alice") == []

        decided = client.put(
            f"/api/review/findings/{finding.id}/decision", json={"review": "ACCEPT"},
            headers={"Authorization": "Bearer alice"},
        )
        assert decided.status_code == 200
        entries = memory.list_entries("alice", source)
        assert len(entries) == 1
        assert entries[0].requirement_text == "Password length must be twelve characters"

        result = client.get(
            f"/api/review/cases/{second.id}/requirements/req-2/suggestions",
            headers={"Authorization": "Bearer alice"},
        )
        assert result.status_code == 200
        assert len(result.json()) == 1
        suggestion = result.json()[0]
        assert suggestion["prior_decision"] == "ACCEPT"
        assert "confirmed" not in suggestion and "review" not in suggestion

        bob_case, _, _ = _seed(runtime, "bob", source, "bob-req")
        bob_result = client.get(
            f"/api/review/cases/{bob_case.id}/requirements/bob-req/suggestions",
            headers={"Authorization": "Bearer bob"},
        )
        assert bob_result.status_code == 200 and bob_result.json() == []
        assert first.id != second.id
    finally:
        runtime.runner.shutdown()


def test_suggestions_are_read_only_owner_scoped_and_return_error_bodies():
    client, runtime = _api(InMemoryMemoryStore())
    try:
        alice_case, _, _ = _seed(runtime, "alice", "source", "alice-req")
        response = client.get(
            f"/api/review/cases/{alice_case.id}/requirements/alice-req/suggestions"
        )
        assert response.status_code == 401

        foreign = client.get(
            f"/api/review/cases/{alice_case.id}/requirements/alice-req/suggestions",
            headers={"Authorization": "Bearer bob"},
        )
        assert foreign.status_code == 404
        assert set(foreign.json()) == {"code", "message"}

        unknown_requirement = client.get(
            f"/api/review/cases/{alice_case.id}/requirements/missing/suggestions",
            headers={"Authorization": "Bearer alice"},
        )
        assert unknown_requirement.status_code == 404
        assert set(unknown_requirement.json()) == {"code", "message"}

        unknown_case = client.get(
            "/api/review/cases/missing/requirements/alice-req/suggestions",
            headers={"Authorization": "Bearer alice"},
        )
        assert unknown_case.status_code == 404
        assert set(unknown_case.json()) == {"code", "message"}
        assert runtime.repository.get_requirements("alice", alice_case.id)[0].confirmed is False
        assert runtime.repository.get_findings("alice", alice_case.id)[0].review == Decision.NONE
    finally:
        runtime.runner.shutdown()


def test_no_memory_store_preserves_decision_behavior_and_returns_no_suggestions():
    client, runtime = _api(None)
    try:
        case, _, finding = _seed(runtime, "alice", "source", "req")
        response = client.put(
            f"/api/review/findings/{finding.id}/decision", json={"review": "REJECT"},
            headers={"Authorization": "Bearer alice"},
        )
        assert response.status_code == 200
        suggestions = client.get(
            f"/api/review/cases/{case.id}/requirements/req/suggestions",
            headers={"Authorization": "Bearer alice"},
        )
        assert suggestions.status_code == 200 and suggestions.json() == []
        assert runtime.repository.get_findings("alice", case.id)[0].review == Decision.REJECT
    finally:
        runtime.runner.shutdown()
