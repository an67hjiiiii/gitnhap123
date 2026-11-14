import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("size,expected", [(2_000_000, 200), (2_000_001, 413)])
def test_import_file_size_boundary(monkeypatch, tmp_path, size, expected):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("STORAGE_BACKEND", "file")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main, "current_user", lambda request: {"user_id": "alice"})
    monkeypatch.setattr(main, "owner_source_store", lambda user: _Store())
    client = TestClient(main.app)
    response = client.post("/api/sources/file", files={"file": ("file.txt", b"x" * size, "text/plain")})
    assert response.status_code == expected


class _Store:
    def import_text(self, name, text, provenance):
        return {"source_id": "s1", "status": "READY"}


def test_import_file_rejects_oversized_content_length_without_reading(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_STORAGE_BACKEND", "file")
    monkeypatch.setenv("STORAGE_BACKEND", "file")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    from app import main

    class Unreadable:
        filename = "file.txt"
        content_type = "text/plain"

        async def read(self, size):
            raise AssertionError("oversized upload was read")

    monkeypatch.setattr(main, "current_user", lambda request: {"user_id": "alice"})
    request = SimpleNamespace(headers={"content-length": "2000001", "content-type": "text/plain"})
    with pytest.raises(main.HTTPException) as error:
        asyncio.run(main.import_file(request, Unreadable()))
    assert error.value.status_code == 413
