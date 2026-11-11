"""Kiểm thử router /api/studio bằng phụ thuộc giả (không cần PostgreSQL/Ollama)."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.studio import ADMIN_TABLES, build_router
from app.core.types import SourceChunk


class FakeStore:
    def chunks(self, source_ids=None):
        return [SourceChunk("c1", "s1", "a.md", "Quy tắc bốn mắt", 0, 0.0)]


class FakePipeline:
    retrieval_backend = "lexical"
    source_store = FakeStore()

    def _retrieve_candidates(self, query, chunks, *, top_k, min_score, source_ids, fallback_trace):
        return [SourceChunk(c.chunk_id, c.source_id, c.source_name, c.text, c.index, 0.73) for c in chunks][:top_k]

    async def run(self, message, condition):
        return {"run_id": f"run_{condition}", "condition": condition, "status": "COMPLETE"}


def client(role="USER", logged_in=True, session=None):
    def current_user(request):
        if not logged_in:
            raise HTTPException(401, "Authentication is required")
        return {"user_id": "u1", "role": role}
    app = FastAPI()
    app.include_router(build_router(current_user=current_user, owner_pipeline=lambda user, *a: FakePipeline(),
                                    session_factory=lambda: session))
    return TestClient(app)


def test_retrieval_test_returns_scored_hits():
    r = client().post("/api/studio/retrieval-test", json={"query": "duyệt", "top_k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["results"][0]["score"] == 0.73 and body["total_chunks"] == 1


def test_requires_login():
    assert client(logged_in=False).post("/api/studio/retrieval-test", json={"query": "x"}).status_code == 401


def test_compare_runs_each_condition_in_order():
    r = client().post("/api/studio/compare", json={"message": "m", "conditions": ["a", "C"]})
    assert [run["condition"] for run in r.json()["runs"]] == ["A", "C"]


def test_admin_routes_forbid_non_admin_and_need_postgres():
    assert client(role="USER").get("/api/studio/admin/overview").status_code == 403
    assert client(role="ADMIN", session=None).get("/api/studio/admin/overview").status_code == 503


def test_admin_table_whitelist_hides_secrets():
    assert client(role="ADMIN", session=object()).get("/api/studio/admin/table/pg_shadow").status_code == 404
    flat = {c for cols in ADMIN_TABLES.values() for c in cols}
    assert "password_hash" not in flat and "token_hash" not in flat


class FakeOwnerStore:
    def __init__(self, items): self.items = items
    def source(self, sid): return self.items.get(sid)


class FakeVectors:
    def __init__(self): self.deleted = []
    def delete(self, ids): self.deleted.extend(ids)


class FakeDB:
    def __init__(self, log): self.log = log
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params): self.log.append((str(sql), params))
    def commit(self): self.log.append('commit')


def delete_client(items, vectors, log):
    def current_user(request): return {"user_id": "u1", "role": "USER"}
    app = FastAPI()
    app.include_router(build_router(current_user=current_user, owner_pipeline=lambda user, *a: FakePipeline(),
                                    session_factory=lambda: (lambda: FakeDB(log)),
                                    owner_source_store=lambda user: FakeOwnerStore(items), vector_store=lambda: vectors))
    return TestClient(app)


def test_delete_source_removes_vectors_and_row_scoped_to_owner():
    vectors, log = FakeVectors(), []
    c = delete_client({"s1": {"chunks": [{"chunk_id": "s1_c0"}, {"chunk_id": "s1_c1"}]}}, vectors, log)
    r = c.delete("/api/studio/sources/s1")
    assert r.status_code == 200 and r.json()["chunks_removed"] == 2
    assert vectors.deleted == ["u1:s1_c0", "u1:s1_c1"]
    sql, params = log[0]
    assert "owner_user_id" in sql and params == {"s": "s1", "o": "u1"} and log[-1] == 'commit'


def test_delete_source_of_someone_else_is_404():
    # Kho của người dùng không thấy tài liệu người khác -> 404, không xóa gì.
    vectors, log = FakeVectors(), []
    assert delete_client({}, vectors, log).delete("/api/studio/sources/khac").status_code == 404
    assert vectors.deleted == [] and log == []
