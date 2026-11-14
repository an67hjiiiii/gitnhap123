"""Additive spec-change HTTP routing and persistence without external services."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.review import ReviewRuntime, build_router
from app.review.repository import InMemoryCaseRepository
from app.review.schemas import ReviewCase
from app.review_adapters.pg_repository import PostgresCaseRepository
from app.storage.postgres.base import Base
from app.storage.postgres.review_models import ReviewCaseRecord
from app.storage.source_store import SourceStore


def document(paths):
    return json.dumps({"openapi": "3.0.3", "info": {"title": "API", "version": "1"},
                       "paths": paths})


@pytest.fixture(params=["memory", "sqlite", "memory-sources", "sqlite-memory-sources"])
def api(request, monkeypatch, sf1_vector_store):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("REVIEW_ENGINE", "fake")
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    if request.param.endswith("sources"):
        # Exercise the owner-store protocol independently of file persistence.
        old, new, foreign = "old", "new", "foreign"
        documents = {"alice": {old: document({"/pets": {"get": {}}}), new: document({})},
                     "bob": {foreign: document({})}}

        def owner_store(owner):
            def source(source_id):
                text = documents[owner].get(source_id)
                return None if text is None else {"chunks": [{"index": 0, "text": text}]}

            return SimpleNamespace(source=source, chunks=lambda source_ids: [])

        stores = {owner: owner_store(owner) for owner in documents}
    else:
        tmp_path = request.getfixturevalue("tmp_path")
        stores = {owner: SourceStore(str(tmp_path / owner)) for owner in ("alice", "bob")}
        old = stores["alice"].import_text("old.json", document({"/pets": {"get": {}}}))["source_id"]
        new = stores["alice"].import_text("new.json", document({}))["source_id"]
        foreign = stores["bob"].import_text("foreign.json", document({}))["source_id"]
    database = None
    options = {"storage_backend": "file"}
    if request.param.startswith("sqlite"):
        database = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
        tables = [table for table in Base.metadata.sorted_tables if table.name.startswith("review_")]
        Base.metadata.create_all(database, tables=tables)
        options = {"storage_backend": "postgres", "session_factory": sessionmaker(database)}
    runtime = ReviewRuntime(source_store_factory=lambda owner: stores[owner], **options)
    app = FastAPI()

    def current_user(request: Request):
        return {"user_id": request.headers.get("x-user", "alice")}

    app.include_router(build_router(current_user=current_user, runtime=runtime))
    try:
        with TestClient(app) as client:
            yield client, runtime, old, new, foreign
    finally:
        runtime.runner.shutdown()
        if database is not None:
            database.dispose()


def create(client, old, new, **extra):
    return client.post("/api/review/cases", json={
        "title": "API changes", "request_text": "Review changed API",
        "kind": "spec_change", "old_source_id": old, "new_source_id": new, **extra,
    })


def confirmed(client, case_id, count=1):
    response = client.put(f"/api/review/cases/{case_id}/requirements", json={
        "requirements": [{"text": "GET /pets", "confirmed": True} for _ in range(count)],
    })
    assert response.status_code == 200, response.text
    return response.json()


def run(client, runtime, case_id, budget=None):
    response = client.post(f"/api/review/cases/{case_id}/runs", json={"budget": budget})
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    runtime.runner.wait(job_id, timeout=5)
    return job_id, client.get(f"/api/review/cases/{case_id}").json()


def test_spec_change_routes_deterministically_and_keeps_change_evidence(api):
    client, runtime, old, new, _ = api
    response = create(client, old, new)
    assert response.status_code == 201, response.text
    case_id = response.json()["id"]
    assert response.json()["kind"] == "spec_change"
    proposals = client.post(f"/api/review/cases/{case_id}/requirements:propose").json()
    assert proposals and "GET /pets" in proposals[0]["text"]
    confirmed(client, case_id)
    job_id, case = run(client, runtime, case_id)
    assert case["old_source_id"] == old and case["new_source_id"] == new
    assert case["status"] == "COMPLETE"
    finding, = case["findings"]
    assert finding["verdict"] == "DEVIATES"
    assert finding["evidence"] == [{"evidence_id": "chg:1", "source_id": old,
                                    "locator": "/pets", "excerpt": "Endpoint removed"}]
    events = runtime.events.read_since(job_id, 0)
    assert events[0].type == "route.decided"
    assert events[0].data["route"] == "DETERMINISTIC" and events[0].data["reasons"]
    inspector = client.get(f"/api/review/cases/{case_id}/inspector").json()
    assert inspector["run"]["route_decision"] == events[0].data
    assert inspector["case"]["kind"] == "spec_change"


@pytest.mark.parametrize("which", ["old", "new"])
def test_foreign_source_is_not_found(api, which):
    client, _, old, new, foreign = api
    response = create(client, foreign if which == "old" else old,
                      foreign if which == "new" else new)
    assert response.status_code == 404
    assert response.json()["code"] == "SOURCE_NOT_FOUND"


@pytest.mark.parametrize("pair", [{}, {"old_source_id": "old"}, {"new_source_id": "new"},
                                  {"old_source_id": "", "new_source_id": "new"}])
def test_missing_source_pair_is_validation_error(api, pair):
    client, _, _, _, _ = api
    response = client.post("/api/review/cases", json={
        "title": "Changes", "request_text": "Review API", "kind": "spec_change", **pair,
    })
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_default_kind_and_ignored_pair_preserve_requirement_review(api):
    client, runtime, _, _, foreign = api
    response = client.post("/api/review/cases", json={
        "title": "Audit", "request_text": "Review policy",
        "old_source_id": foreign, "new_source_id": "missing",
    })
    assert response.status_code == 201
    case_id = response.json()["id"]
    assert response.json()["kind"] == "requirement_review"
    assert response.json()["old_source_id"] is None and response.json()["new_source_id"] is None
    confirmed(client, case_id)
    job_id, case = run(client, runtime, case_id)
    assert case["findings"][0]["verdict"] == "SATISFIED"
    assert runtime.events.read_since(job_id, 0)[0].data["route"] == "MULTI_AGENT"


def test_budget_never_silently_drops_spec_change_requirements(api):
    client, runtime, old, new, _ = api
    case_id = create(client, old, new).json()["id"]
    requirements = confirmed(client, case_id, count=2)
    _, case = run(client, runtime, case_id, {"max_requirements": 1, "max_model_calls": 0, "max_tokens": 0})
    assert [item["verdict"] for item in case["findings"]] == ["DEVIATES", "SKIPPED_BUDGET"]
    inspector = client.get(f"/api/review/cases/{case_id}/inspector").json()
    assert inspector["budget"]["skipped_requirement_ids"] == [requirements[1]["id"]]
    assert inspector["run"]["state"] == "PARTIAL"


@pytest.mark.parametrize("budget", [{"max_model_calls": 1}, {"max_tokens": 3}])
def test_budget_manager_degrades_requirement_plan(api, budget):
    client, runtime, _, _, _ = api
    case_id = client.post("/api/review/cases", json={
        "title": "Audit", "request_text": "Check policies",
    }).json()["id"]
    requirements = confirmed(client, case_id, count=3)
    _, case = run(client, runtime, case_id, budget)
    assert len(case["findings"]) == len(requirements)
    assert [item["verdict"] for item in case["findings"]] == [
        "SATISFIED", "SKIPPED_BUDGET", "SKIPPED_BUDGET",
    ]
    inspector = client.get(f"/api/review/cases/{case_id}/inspector").json()
    assert inspector["budget"]["skipped_requirement_ids"] == [r["id"] for r in requirements[1:]]


def test_null_budget_limits_preserve_unlimited_behavior(api):
    client, runtime, old, new, _ = api
    case_id = create(client, old, new).json()["id"]
    confirmed(client, case_id)
    _, case = run(client, runtime, case_id, {
        "max_requirements": None, "max_seconds": None, "max_tokens": None, "max_model_calls": None,
    })
    assert case["findings"][0]["verdict"] == "DEVIATES"


def test_source_ownership_is_checked_again_before_run(api):
    client, runtime, old, new, _ = api
    case_id = create(client, old, new).json()["id"]
    confirmed(client, case_id)
    runtime.source_store_factory = lambda owner: SimpleNamespace(source=lambda source_id: None)
    response = client.post(f"/api/review/cases/{case_id}/runs")
    assert response.status_code == 404 and response.json()["code"] == "SOURCE_NOT_FOUND"


def test_source_pair_requires_a_configured_owner_store(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    runtime = ReviewRuntime(storage_backend="file")
    app = FastAPI()
    app.include_router(build_router(current_user=lambda request: {"user_id": "alice"}, runtime=runtime))
    try:
        with TestClient(app) as client:
            assert create(client, "old", "new").json()["code"] == "SOURCE_NOT_FOUND"
    finally:
        runtime.runner.shutdown()


def test_in_memory_source_pair_round_trip_is_detached(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    case = ReviewCase(id="case", owner_user_id="alice", title="API", request_text="Compare",
                      kind="spec_change", old_source_id="old", new_source_id="new",
                      created_at=now, updated_at=now)
    repo = InMemoryCaseRepository()
    repo.save_case("alice", case)
    loaded = repo.get_case("alice", case.id)
    assert loaded == case
    loaded.old_source_id = "other"
    assert repo.get_case("alice", case.id) == case
    assert repo.get_case("bob", case.id) is None


def test_sqlite_kind_meta_round_trip(monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine, tables=[ReviewCaseRecord.__table__])
        factory = sessionmaker(engine)
        repo = PostgresCaseRepository(factory)
        now = datetime(2026, 11, 14, tzinfo=timezone.utc)
        case = ReviewCase(id="case", owner_user_id="alice", title="API", request_text="Compare",
                          kind="spec_change", old_source_id="old", new_source_id="new",
                          created_at=now, updated_at=now)
        repo.save_case("alice", case)
        assert PostgresCaseRepository(factory).get_case("alice", case.id) == case
        with factory() as session:
            row = session.scalar(select(ReviewCaseRecord))
            assert row.kind == "spec_change"
            assert row.meta == {"old_source_id": "old", "new_source_id": "new"}
        case.kind, case.old_source_id, case.new_source_id = "requirement_review", None, None
        repo.save_case("alice", case)
        assert repo.get_case("alice", case.id) == case
        with factory() as session:
            assert session.scalar(select(ReviewCaseRecord)).meta is None
    finally:
        engine.dispose()
