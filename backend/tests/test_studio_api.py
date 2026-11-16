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

    async def run(self, message, condition, source_ids=None):
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
    def get(self, model, sid):  # tài liệu cá nhân của u1
        from types import SimpleNamespace
        return SimpleNamespace(source_id=sid, owner_user_id="u1", space_id=None, department_id=None, classification="PRIVATE")


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
    # quyền xóa đã kiểm bằng app.core.access trước khi chạy câu lệnh
    assert sql.startswith("DELETE FROM knowledge_sources") and params == {"s": "s1"} and log[-1] == 'commit'


def test_delete_source_of_someone_else_is_404():
    # Kho của người dùng không thấy tài liệu người khác -> 404, không xóa gì.
    vectors, log = FakeVectors(), []
    assert delete_client({}, vectors, log).delete("/api/studio/sources/khac").status_code == 404
    assert vectors.deleted == [] and log == []


class RecordingDb:
    """Phiên CSDL giả: ghi câu SQL và tham số, trả về bảng rỗng."""
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params or {}))
        return self

    def mappings(self):
        return self

    def all(self):
        return []

    def scalar(self):
        return 0


def test_admin_table_search_filters_with_bound_parameter():
    db = RecordingDb()
    r = client(role="ADMIN", session=lambda: db).get("/api/studio/admin/table/users?q=chung'--")
    assert r.status_code == 200
    select_sql, params = db.calls[0]
    count_sql, count_params = db.calls[1]
    assert "ILIKE :q" in select_sql and "ILIKE :q" in count_sql
    assert params["q"] == "%chung'--%" and count_params["q"] == "%chung'--%"
    assert "chung" not in select_sql


def test_admin_table_without_search_has_no_filter():
    db = RecordingDb()
    client(role="ADMIN", session=lambda: db).get("/api/studio/admin/table/users")
    assert "WHERE" not in db.calls[0][0]


class DomainPipeline(FakePipeline):
    class Store:
        def chunks(self, source_ids=None):
            return [SourceChunk("c1", "s1", "a.md", "Bảng payments có khóa chính và chỉ mục database", 0, 0.0),
                    SourceChunk("c2", "s1", "a.md", "Cookie phiên và xác thực đăng nhập authentication", 1, 0.0)]
    source_store = Store()


def test_retrieval_test_filters_by_domain_and_tags_hits():
    app = FastAPI()
    app.include_router(build_router(current_user=lambda r: {"user_id": "u1", "role": "USER"},
                                    owner_pipeline=lambda user, *a: DomainPipeline(), session_factory=lambda: None))
    c = TestClient(app)
    all_hits = c.post("/api/studio/retrieval-test", json={"query": "x", "top_k": 5}).json()["results"]
    assert {h["chunk_id"]: h["domains"] for h in all_hits} == {"c1": ["database"], "c2": ["security"]}
    sec = c.post("/api/studio/retrieval-test", json={"query": "x", "top_k": 5, "domain": "security"}).json()["results"]
    assert [h["chunk_id"] for h in sec] == ["c2"]
    assert c.post("/api/studio/retrieval-test", json={"query": "x", "domain": "nope"}).status_code == 422
