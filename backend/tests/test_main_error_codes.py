from fastapi.testclient import TestClient


def test_empty_text_uses_structured_error(monkeypatch):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("PROVIDER", "fake")
    from app import main

    monkeypatch.setattr(main, "current_user", lambda request: {"user_id": "alice"})
    with TestClient(main.app) as client:
        response = client.post("/api/sources/text", json={"source_name": "note.txt", "text": "  "})
    assert response.status_code == 400
    assert response.json() == {"code": "EMPTY_TEXT", "message": "Request could not be completed"}
