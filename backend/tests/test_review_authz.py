"""Owner isolation and authentication coverage for every review operation."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.auth import get_session_token, router as auth_router
from app.api.review import ReviewRuntime, build_router, get_review_engine
from app.auth.store import AuthStore, InvalidSessionError
from app.review.engine import FakeReviewEngine
from app.storage.source_store import SourceStore
from app.storage.vector_store import InMemoryVectorStore


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "contracts" / "review" / "openapi.review.v0.json"
ROUTES = {
    ("GET", "/api/review/cases"),
    ("POST", "/api/review/cases"),
    ("GET", "/api/review/cases/{case_id}"),
    ("GET", "/api/review/cases/{case_id}/export"),
    ("GET", "/api/review/cases/{case_id}/inspector"),
    ("PUT", "/api/review/cases/{case_id}/requirements"),
    ("GET", "/api/review/cases/{case_id}/requirements/{requirement_id}/suggestions"),
    ("POST", "/api/review/cases/{case_id}/requirements:propose"),
    ("POST", "/api/review/cases/{case_id}/runs"),
    ("PUT", "/api/review/findings/{finding_id}/decision"),
    ("GET", "/api/review/runs/{job_id}"),
    ("GET", "/api/review/runs/{job_id}/events"),
    ("POST", "/api/review/runs/{job_id}:cancel"),
}


@pytest.fixture
def auth_api(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("REVIEW_ENGINE", "fake")
    monkeypatch.delenv("AUTH_BOOTSTRAP_ADMIN", raising=False)
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    vector_store = InMemoryVectorStore()
    assert vector_store is not None
    store = AuthStore(tmp_path / "auth")
    source_stores = {name: SourceStore(tmp_path / name) for name in ("alice", "bob")}
    owner_stores = {}
    sources = {
        name: source_stores[name].import_text("source.txt", f"A documented policy for {name}.")['source_id']
        for name in source_stores
    }
    runtime = ReviewRuntime(source_store_factory=lambda owner: owner_stores.get(owner))
    app = FastAPI()
    app.state.auth_store = store
    app.include_router(auth_router)

    def current_user(request: Request):
        try:
            return store.resolve(get_session_token(request))
        except InvalidSessionError as exc:
            raise HTTPException(401, "Authentication is required") from exc

    app.include_router(build_router(current_user=current_user, runtime=runtime))
    app.dependency_overrides[get_review_engine] = lambda: FakeReviewEngine()
    try:
        with TestClient(app) as client:
            tokens = {}
            for name in ("alice", "bob"):
                client.post("/api/auth/register", json={
                    "username": name, "email": f"{name}@example.test", "password": "test-password-123",
                }).raise_for_status()
                login = client.post("/api/auth/login", json={
                    "identifier": name, "password": "test-password-123",
                })
                assert login.status_code == 200
                tokens[name] = login.json()["access_token"]
                user = store.resolve(tokens[name])
                owner_stores[user["user_id"]] = source_stores[name]
            yield client, runtime, store, tokens, sources
    finally:
        runtime.runner.shutdown()


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _assert_error_body(response, code):
    schema = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["components"]["schemas"]["ErrorBody"]
    body = response.json()
    assert response.status_code == 404
    assert set(schema.get("required", [])) <= body.keys()
    assert body.keys() <= schema["properties"].keys()
    assert body["code"] == code
    assert isinstance(body["message"], str)


def _create(client, token, source_id, *, kind="requirement_review", **extra):
    body = {"title": "Policy review", "request_text": "Review the policy.",
            "source_ids": [source_id], "kind": kind, **extra}
    response = client.post("/api/review/cases", json=body, headers=_headers(token))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ready(client, runtime, token, source_id):
    case_id = _create(client, token, source_id)
    proposed = client.post(f"/api/review/cases/{case_id}/requirements:propose",
                           headers=_headers(token)).json()
    confirmed = [{"id": item["id"], "text": item["text"], "confirmed": True} for item in proposed]
    assert client.put(f"/api/review/cases/{case_id}/requirements",
                      json={"requirements": confirmed}, headers=_headers(token)).status_code == 200
    result = client.post(f"/api/review/cases/{case_id}/runs", headers=_headers(token), json={})
    assert result.status_code == 202, result.text
    job_id = result.json()["id"]
    runtime.runner.wait(job_id, timeout=5)
    finding = client.get(f"/api/review/cases/{case_id}", headers=_headers(token)).json()["findings"][0]
    return case_id, job_id, finding


def test_auth_matrix_covers_every_openapi_route():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    documented = {(method.upper(), path) for path, methods in snapshot["paths"].items()
                  for method in methods if method.lower() in {"get", "post", "put", "delete", "patch"}}
    assert documented == ROUTES


def test_foreign_owner_cannot_access_case_requirements_run_finding_export_or_inspector(auth_api):
    client, runtime, _, tokens, sources = auth_api
    case_id, job_id, finding = _ready(client, runtime, tokens["alice"], sources["alice"])
    requirements = client.get(f"/api/review/cases/{case_id}", headers=_headers(tokens["alice"])).json()["requirements"]
    requirement_id = requirements[0]["id"]
    route_cases = [
        ("GET", f"/cases/{case_id}", None),
        ("GET", f"/cases/{case_id}/inspector", None),
        ("PUT", f"/cases/{case_id}/requirements", {"requirements": []}),
        ("GET", f"/cases/{case_id}/requirements/{requirement_id}/suggestions", None),
        ("POST", f"/cases/{case_id}/requirements:propose", None),
        ("POST", f"/cases/{case_id}/runs", {}),
        ("GET", f"/cases/{case_id}/export", None),
        ("GET", f"/runs/{job_id}", None),
        ("GET", f"/runs/{job_id}/events", None),
        ("POST", f"/runs/{job_id}:cancel", None),
        ("PUT", f"/findings/{finding['id']}/decision", {"review": "ACCEPT"}),
    ]
    for method, path, body in route_cases:
        response = client.request(method, "/api/review" + path, json=body,
                                  headers=_headers(tokens["bob"]))
        _assert_error_body(response, "FINDING_NOT_FOUND" if method == "PUT" and "/findings/" in path
                           else "CASE_NOT_FOUND")
    listed = client.get("/api/review/cases", headers=_headers(tokens["bob"]))
    assert listed.status_code == 200
    assert all(case["id"] != case_id for case in listed.json())


def test_foreign_sources_are_not_accepted_for_review_or_spec_change(auth_api):
    client, _, _, tokens, sources = auth_api
    payload = {"title": "Foreign source", "request_text": "Review", "source_ids": [sources["alice"]]}
    response = client.post("/api/review/cases", json=payload, headers=_headers(tokens["bob"]))
    assert response.status_code == 404 and response.json()["code"] == "SOURCE_NOT_FOUND"
    for old_id, new_id in ((sources["alice"], sources["bob"]),
                           (sources["bob"], sources["alice"])):
        response = client.post("/api/review/cases", json={
            "title": "Spec change", "request_text": "Compare", "kind": "spec_change",
            "old_source_id": old_id, "new_source_id": new_id,
        }, headers=_headers(tokens["bob"]))
        assert response.status_code == 404 and response.json()["code"] == "SOURCE_NOT_FOUND"


def test_finding_guess_and_foreign_case_context_are_hidden(auth_api):
    client, runtime, _, tokens, sources = auth_api
    _, _, finding = _ready(client, runtime, tokens["alice"], sources["alice"])
    bob_case = _create(client, tokens["bob"], sources["bob"])
    response = client.put(f"/api/review/findings/{finding['id']}/decision",
                          json={"review": "ACCEPT"}, headers=_headers(tokens["bob"]))
    _assert_error_body(response, "FINDING_NOT_FOUND")
    response = client.get(f"/api/review/cases/{bob_case}/inspector?run={finding['id']}",
                          headers=_headers(tokens["bob"]))
    _assert_error_body(response, "RUN_NOT_FOUND")


def test_all_review_routes_require_valid_bearer_sessions(auth_api):
    client, runtime, store, tokens, sources = auth_api
    case_id, job_id, finding = _ready(client, runtime, tokens["alice"], sources["alice"])
    requirements = client.get(f"/api/review/cases/{case_id}", headers=_headers(tokens["alice"])).json()["requirements"]
    requirement_id = requirements[0]["id"]
    requests = [
        ("GET", "/api/review/cases", "/cases", None),
        ("POST", "/api/review/cases", "/cases", {"title": "x", "request_text": "x"}),
        ("GET", "/api/review/cases/{case_id}", f"/cases/{case_id}", None),
        ("GET", "/api/review/cases/{case_id}/export", f"/cases/{case_id}/export", None),
        ("GET", "/api/review/cases/{case_id}/inspector", f"/cases/{case_id}/inspector", None),
        ("PUT", "/api/review/cases/{case_id}/requirements", f"/cases/{case_id}/requirements", {"requirements": []}),
        ("GET", "/api/review/cases/{case_id}/requirements/{requirement_id}/suggestions",
         f"/cases/{case_id}/requirements/{requirement_id}/suggestions", None),
        ("POST", "/api/review/cases/{case_id}/requirements:propose", f"/cases/{case_id}/requirements:propose", None),
        ("POST", "/api/review/cases/{case_id}/runs", f"/cases/{case_id}/runs", {}),
        ("PUT", "/api/review/findings/{finding_id}/decision", f"/findings/{finding['id']}/decision", {"review": "ACCEPT"}),
        ("GET", "/api/review/runs/{job_id}", f"/runs/{job_id}", None),
        ("GET", "/api/review/runs/{job_id}/events", f"/runs/{job_id}/events", None),
        ("POST", "/api/review/runs/{job_id}:cancel", f"/runs/{job_id}:cancel", None),
    ]
    covered = {(method, template) for method, template, _, _ in requests}
    assert covered == ROUTES
    client.cookies.clear()  # login cookie would otherwise authenticate the 'no header' requests
    for method, _, path, body in requests:
        for headers in ({}, _headers("invalid-token")):
            response = client.request(method, "/api/review" + path, json=body, headers=headers)
            assert response.status_code == 401
            assert response.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert store.resolve(tokens["alice"])
    session = next(item for item in store._data["sessions"] if item["user_id"] == store.resolve(tokens["alice"])["user_id"])
    session["expires_at"] = "2000-01-01T00:00:00+00:00"
    store._save()
    for method, _, path, body in requests:
        response = client.request(method, "/api/review" + path, json=body,
                                  headers=_headers(tokens["alice"]))
        assert response.status_code == 401

