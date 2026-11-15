"""Tự lập lại chỉ mục khi embedding_version đổi: nền, theo nguồn, không xoá, thông báo thân thiện."""
import sys
from dataclasses import replace

from app.retrieval.candidate_index import CandidateIndex
from app.retrieval.index_identity import IndexManifest, IndexState
from app.retrieval.reindex import ReindexManager, index_state
from app.storage.source_store import SourceStore
from app.storage.vector_store import InMemoryVectorStore
from tests.test_chat_endpoint import chat_http  # noqa: F401


def _stale_index(tmp_path):
    store = SourceStore(str(tmp_path / "s"))
    a = store.import_text("a.md", "# Nhật ký\n\nNhật ký truy cập giữ 365 ngày.\n\n# Mật khẩu\n\nMật khẩu hết hạn sau 90 ngày.")
    b = store.import_text("b.md", "Bản sao lưu được mã hoá hằng đêm.")
    vectors = InMemoryVectorStore(vector_size=768)
    index = CandidateIndex(store, vectors, owner_user_id="u1")
    for s in (a, b):
        index.index_source(s["source_id"])
    old = replace(index.identity, embedding_version="old-v0")  # simulate vectors built by an older embedder
    index._write_manifest(IndexManifest(old, payload_complete=True))
    return store, vectors, index, [a["source_id"], b["source_id"]]


def test_incompatible_index_is_rebuilt_in_background_without_deleting(tmp_path):
    store, vectors, index, ids = _stale_index(tmp_path)
    assert index_state(index) == IndexState.INCOMPATIBLE
    before = vectors.count()
    manager = ReindexManager()
    assert manager.start(lambda owner: index, [("u1", s) for s in ids], prepare=index.begin_rebuild)
    manager.wait(30)
    status = manager.status()
    assert status["status"] == "done" and status["done"] == status["total"] == 2 and status["failed"] == 0
    assert index_state(index) == IndexState.COMPATIBLE
    assert vectors.count() >= before  # nothing deleted
    assert index.candidates("mật khẩu hết hạn", limit=3)  # searchable again


def test_second_start_while_running_is_refused_and_one_failing_source_does_not_stop_others(tmp_path):
    store, vectors, index, ids = _stale_index(tmp_path)
    manager = ReindexManager()

    class Boom:
        def __init__(self, real): self.real = real
        def index_source(self, sid):
            if sid == ids[0]:
                raise RuntimeError("boom")
            return self.real.index_source(sid)

    assert manager.start(lambda owner: Boom(index), [("u1", s) for s in ids], prepare=index.begin_rebuild)
    manager.wait(30)
    status = manager.status()
    assert status["status"] == "failed" and status["failed"] == 1 and status["done"] == 2


def test_document_question_gets_friendly_message_while_reindexing(chat_http):  # noqa: F811
    chat_http.post("/api/sources/text", json={"source_name": "a.md", "text": "Mật khẩu hết hạn sau 90 ngày."})
    module = sys.modules["app._chat_endpoint_main"]
    module._REINDEX._state.update(status="running", done=2, total=5)
    body = chat_http.post("/api/chat", json={"message": "Mật khẩu hết hạn sau bao lâu?", "product_mode": True}).json()
    assert body["events"][0]["path"] == "REINDEXING" and body["run_id"] is None
    assert "Đang cập nhật chỉ mục tài liệu (2/5)" in body["answer"]
    assert body["index"]["done"] == 2 and chat_http.get("/api/index/status").json()["total"] == 5
    # direct answers are not blocked
    direct = chat_http.post("/api/chat", json={"message": "Tính 12 + 30 bằng bao nhiêu?", "product_mode": True}).json()
    assert direct["events"][0]["path"] == "DIRECT"
    module._REINDEX._state.update(status="idle")
