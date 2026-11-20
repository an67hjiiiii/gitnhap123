"""Đợt 7: điều kiện AUTO (tự quyết) trong Phòng đánh giá chạy đúng luồng ô chat sản phẩm; C giữ nguyên."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.analysis import build_router


def client(calls):
    class Pipe:
        async def run(self, question, condition, **kw):
            calls.append((condition, kw))
            return {"run_id": "r", "status": "COMPLETE", "answer": "Thử việc tối đa 60 ngày.", "metrics": {}, "tasks": [],
                    "effective_config": {"request_route": "SIMPLE_PROJECT_QUESTION"} if kw.get("product_mode") else {}}

    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u"}, owner_pipeline=lambda user, *a: Pipe(), session_factory=lambda: None))
    return TestClient(app)


def test_auto_runs_product_pipeline_with_work_agents_and_c_stays_as_before(monkeypatch):
    monkeypatch.setenv("IMPLEMENTATION_PROFILE", "m2")
    calls = []
    c = client(calls)
    auto = c.post("/api/studio/eval/run", json={"question": "Thử việc tối đa bao lâu?", "condition": "AUTO", "key_points": ["60 ngày"]}).json()
    plain = c.post("/api/studio/eval/run", json={"question": "Thử việc tối đa bao lâu?", "condition": "C", "key_points": ["60 ngày"]}).json()
    assert calls[0] == ("C", {"source_ids": None, "reply_in_query_language": True, "product_mode": True, "domain_pack": "work"})
    assert calls[1] == ("C", {"source_ids": None, "reply_in_query_language": True})
    assert auto["condition"] == "AUTO" and auto["route"] == "SIMPLE_PROJECT_QUESTION" and auto["key_point_coverage"] == 1.0
    assert plain["condition"] == "C" and plain["route"] is None
