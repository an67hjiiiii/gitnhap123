from __future__ import annotations

import json
import os
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.office import build_router


class _DummyChunk:
    def __init__(self, chunk_id: str, source_id: str, source_name: str, text: str, score: float = 0.9):
        self.chunk_id = chunk_id
        self.source_id = source_id
        self.source_name = source_name
        self.text = text
        self.score = score


class _DummyPipeline:
    def __init__(self, chunks: list[_DummyChunk]):
        self._chunks = chunks
        self.source_store = SimpleNamespace(chunks=lambda source_ids=None: list(self._chunks))

    def _retrieve_candidates(self, query, chunks, top_k=5, min_score=0.0, source_ids=None):
        return self._chunks[:top_k]


def _make_client(with_docs: bool = True) -> TestClient:
    os.environ["PROVIDER"] = "fake"
    app = FastAPI()
    chunks = [
        _DummyChunk("c1", "src_1", "Quy_Che_Nhan_Su_2026.docx", "Phụ cấp ăn trưa 1.500.000 VNĐ/tháng và nghỉ phép năm 12 ngày."),
        _DummyChunk("c2", "src_2", "Bao_Cao_Tai_Chinh_Q4.xlsx", "Doanh thu thuần 18.000 triệu VNĐ, lợi nhuận trước thuế 6.000 triệu VNĐ."),
    ] if with_docs else []
    router = build_router(
        current_user=lambda request: {"user_id": "usr_test", "role": "USER"},
        owner_pipeline=lambda user: _DummyPipeline(chunks),
        session_factory=lambda: None,
    )
    app.include_router(router)
    return TestClient(app)


def test_work_session_streams_full_multi_agent_workflow_with_docs() -> None:
    client = _make_client(with_docs=True)
    res = client.post("/api/studio/office/work-session", json={"domain_pack": "business_hr"})
    assert res.status_code == 200
    events = [json.loads(line) for line in res.text.strip().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    assert types[0] == "session_start"
    assert "rag_evidence" in types
    assert types[-1] == "session_done"

    messages = [e for e in events if e["type"] == "agent_message"]
    agents = [m["agent_id"] for m in messages]
    # Orchestrator -> Agent A -> Agent B -> Reviewer -> Integrator = 5 lượt trao đổi thật
    assert len(messages) == 5
    assert agents[0] == "orchestrator"
    assert agents[-2] == "reviewer"
    assert agents[-1] == "integrator"


def test_work_session_without_docs_still_runs_real_team_exchange() -> None:
    client = _make_client(with_docs=False)
    res = client.post("/api/studio/office/work-session", json={"domain_pack": "software"})
    assert res.status_code == 200
    events = [json.loads(line) for line in res.text.strip().splitlines() if line.strip()]
    assert events[0]["type"] == "session_start"
    assert events[0]["has_docs"] is False
    assert events[-1]["type"] == "session_done"
    assert len([e for e in events if e["type"] == "agent_message"]) == 5
