"""23/11: dùng lại một AsyncClient trong mỗi vòng lặp sự kiện (tạo mới mỗi lần gọi tốn 0,4–1,5 s, chặn luồng sự kiện ô chat)."""
import asyncio

from app.providers.ollama import _async_client
from app.research import provenance


def test_client_reused_within_loop_and_new_per_loop():
    async def two():
        return _async_client(5.0), _async_client(5.0)
    a, b = asyncio.run(two())
    c, _ = asyncio.run(two())
    assert a is b and c is not a


def test_model_digest_cached(monkeypatch):
    calls = []

    class R:
        def json(self):
            return {"models": [{"name": "m:1", "digest": "abc"}]}
    monkeypatch.setattr(provenance.httpx, "get", lambda *a, **k: calls.append(1) or R())
    provenance._DIGEST_CACHE.clear()
    assert provenance.ollama_model_digest("m:1") == "abc" == provenance.ollama_model_digest("m:1")
    assert len(calls) == 1
