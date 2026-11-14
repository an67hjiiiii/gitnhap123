"""Chat endpoint wiring: intent routing, no retrieval for small talk, SSE progress. Fake provider only."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import dotenv
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def chat_http(monkeypatch, tmp_path, sf1_fake_provider_env, sf1_vector_store):
    import app.auth.store as auth_module

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(auth_module, "AuthStore", lambda *args: SimpleNamespace(
        resolve=lambda token: {"user_id": token, "role": "USER"},
    ))
    for key, value in {
        "APP_STORAGE_BACKEND": "file", "APP_ENV": "test", "APP_DATA_DIR": str(tmp_path / "documents"),
        "RUNS_DIR": str(tmp_path / "outputs"), "VECTOR_BACKEND": "memory",
    }.items():
        monkeypatch.setenv(key, value)
    name = "app._chat_endpoint_main"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app" / "main.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_session_token", lambda request: "alice")
    monkeypatch.setattr(module, "_configured_vector_store", lambda: sf1_vector_store)
    with TestClient(module.app) as client:
        yield client


def test_greeting_is_answered_without_retrieval_or_pipeline(chat_http):
    response = chat_http.post("/api/chat", json={"message": "Xin chào!", "product_mode": True})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"].startswith("Chào bạn")
    assert body["intent"]["intent"] == "greeting"
    assert body["run_id"] is None and body["route"] is None
    assert [event["stage"] for event in body["events"]] == ["intent_routed"]
    assert body["events"][0]["retrieval"] is False


def test_out_of_scope_is_answered_immediately_and_conversation_continues(chat_http):
    first = chat_http.post("/api/chat", json={"message": "Hôm nay thời tiết thế nào?", "product_mode": True}).json()
    assert first["intent"]["intent"] == "out_of_scope" and first["run_id"] is None
    second = chat_http.post("/api/chat", json={
        "message": "Cảm ơn bạn", "product_mode": True, "conversation_id": first["conversation_id"],
    }).json()
    assert second["intent"]["intent"] == "thanks"
    history = chat_http.get(f"/api/conversations/{first['conversation_id']}").json()
    assert [m["role"] for m in history["messages"]] == ["USER", "ASSISTANT", "USER", "ASSISTANT"]


def test_document_question_runs_pipeline_and_reports_route(chat_http):
    source = chat_http.post("/api/sources/text", json={
        "source_name": "policy.txt", "text": "Temporary access grants expire after 45 minutes."})
    assert source.status_code == 200, source.text
    body = chat_http.post("/api/chat", json={
        "message": "When do temporary access grants expire?", "product_mode": True}).json()
    assert body["intent"]["intent"] == "document_question"
    assert body["route"] and body["route"]["path"] in {"B", "C"}
    assert any(event.get("stage") == "route_chosen" for event in body["events"])
    assert body["run_id"]


def test_stream_emits_status_events_then_done(chat_http):
    with chat_http.stream("POST", "/api/chat/stream", json={"message": "Xin chào", "product_mode": True}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    blocks = [b for b in text.strip().split("\n\n") if b]
    names = [b.split("\n")[0] for b in blocks]
    assert names[0] == "event: status" and names[-1] == "event: done"
    done = json.loads(blocks[-1].split("data: ", 1)[1])
    assert done["intent"]["intent"] == "greeting"


def test_stream_reports_friendly_error_for_empty_message(chat_http):
    with chat_http.stream("POST", "/api/chat/stream", json={"message": "   ", "product_mode": True}) as response:
        text = "".join(response.iter_text())
    block = [b for b in text.strip().split("\n\n") if b][-1]
    assert block.startswith("event: error")
    data = json.loads(block.split("data: ", 1)[1])
    assert data["code"] == "MESSAGE_REQUIRED" and data["http_status"] == 400 and data["hint"]
