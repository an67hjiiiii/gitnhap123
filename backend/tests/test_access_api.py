"""Đợt 4 phân quyền: phạm vi của lượt chạy, hội thoại, các API Studio và trang quản trị."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.analysis import build_router as build_analysis_router
from app.api.studio import ORG_MASK, build_router as build_studio_router
from app.core.access import REDACTED_ANSWER, referenced_source_ids, require_active_member
from app.storage.postgres.base import Base
from app.storage.postgres.models import (
    KnowledgeSourceRecord,
    OrgDepartmentRecord,
    OrgMemberRecord,
    OrgSpaceRecord,
    UserRecord,
)
from app.storage.postgres.runtime import PostgresConversationStore, PostgresRunStore, PostgresSourceStore

SP = "sp_abc"
PEOPLE = ["an", "binh", "chi", "em", "ha", "giang"]
DOCS = {  # mã: (người tải lên, phòng, mức mật)
    "bang_gia": ("chi", "d_kd", "DEPARTMENT"),
    "bao_cao_chi": ("chi", "d_kd", "RESTRICTED"),
    "noi_quy": ("an", None, "COMPANY"),
    "sap_nhap": ("an", None, "SECRET"),
}


@pytest.fixture()
def world():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    def _connect(conn, _):
        conn.create_function("btrim", 1, lambda v: None if v is None else v.strip())
        conn.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", _connect)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as s:
        s.add_all([UserRecord(user_id=p, email=f"{p}@x.vn", display_name=p, password_hash="x") for p in PEOPLE])
        s.flush()
        s.add(OrgSpaceRecord(space_id=SP, name="Công ty ABC"))
        s.flush()
        s.add_all([OrgDepartmentRecord(department_id="d_kd", space_id=SP, name="Kinh doanh"),
                   OrgDepartmentRecord(department_id="d_kt", space_id=SP, name="Kế toán")])
        s.flush()
        s.add_all([
            OrgMemberRecord(space_id=SP, user_id="an", level="EXECUTIVE", is_owner=True, status="ACTIVE"),
            OrgMemberRecord(space_id=SP, user_id="binh", department_id="d_kd", level="MANAGER", status="ACTIVE"),
            OrgMemberRecord(space_id=SP, user_id="chi", department_id="d_kd", level="STAFF", status="ACTIVE"),
            OrgMemberRecord(space_id=SP, user_id="em", department_id="d_kt", level="STAFF", status="ACTIVE"),
            OrgMemberRecord(space_id=SP, user_id="ha", level="STAFF", status="PENDING"),
        ])
        # bảng chỉ có trong migration (Studio dùng SQL thô)
        s.execute(text("CREATE TABLE studio_workspace_items (workspace_id TEXT, item_type TEXT, item_id TEXT)"))
    ids = {}
    for code, (owner, dept, level) in DOCS.items():
        ids[code] = PostgresSourceStore(factory, owner).import_text(f"{code}.txt", f"Nội dung tài liệu {code}.")["source_id"]
    with factory.begin() as s:
        for code, (_, dept, level) in DOCS.items():
            row = s.get(KnowledgeSourceRecord, ids[code])
            row.space_id, row.department_id, row.classification = SP, dept, level
    return factory, ids


def _run(run_id, *source_ids):
    return {"run_id": run_id, "created_at": "2026-11-16T00:00:00+00:00", "condition": "A", "query": "câu hỏi",
            "status": "COMPLETED", "answer": "câu trả lời có nội dung tài liệu",
            "task_results": [{"citations": [f"{sid}_c0000" for sid in source_ids]}]}


# ---- cửa vào phạm vi tổ chức

def test_require_active_member(world):
    factory, _ = world
    with factory() as db:
        assert require_active_member(db, "chi", SP).level == "STAFF"
        for outsider in ("ha", "giang"):  # chờ duyệt, không phải thành viên
            with pytest.raises(PermissionError):
                require_active_member(db, outsider, SP)
        with pytest.raises(PermissionError):
            require_active_member(db, "chi", "sp_khong_co")


def test_referenced_source_ids_scans_everything(world):
    _, ids = world
    run = {"answer": "x", "events": [{"candidates": [f"{ids['sap_nhap']}_c0003"]}], "task_results": []}
    assert referenced_source_ids(run) == {ids["sap_nhap"]}


# ---- lượt chạy

def test_runs_are_scoped(world):
    factory, ids = world
    PostgresRunStore(factory, "chi").save(_run("r_ca_nhan"))
    PostgresRunStore(factory, "chi", space_id=SP).save(_run("r_cty", ids["bang_gia"]))
    personal, org = PostgresRunStore(factory, "chi"), PostgresRunStore(factory, "chi", space_id=SP)
    assert [r["run_id"] for r in personal.list()] == ["r_ca_nhan"]
    assert [r["run_id"] for r in org.list()] == ["r_cty"]
    assert [r["run_id"] for r in org.list_light()] == ["r_cty"]
    assert personal.get("r_cty") is None and org.get("r_ca_nhan") is None
    assert org.get("r_cty")["answer"] == "câu trả lời có nội dung tài liệu"
    with pytest.raises(PermissionError):  # không ghi đè lượt chạy sang phạm vi khác
        personal.save(_run("r_cty"))


def test_old_answer_hidden_after_demotion(world):
    factory, ids = world
    store = PostgresRunStore(factory, "binh", space_id=SP)
    store.save(_run("r_binh", ids["bang_gia"], ids["bao_cao_chi"]))
    assert store.get("r_binh")["answer"] != REDACTED_ANSWER
    with factory.begin() as s:
        s.get(OrgMemberRecord, (SP, "binh")).level = "STAFF"
    hidden = store.get("r_binh")
    assert hidden["answer"] == REDACTED_ANSWER and hidden["access_redacted"] is True
    assert hidden["task_results"] == [] and hidden["query"] == "câu hỏi"


def test_conversation_scope_and_redaction(world):
    factory, ids = world
    personal = PostgresConversationStore(factory, "binh")
    org = PostgresConversationStore(factory, "binh", space_id=SP)
    conv = org.create("Hỏi về báo cáo")["conversation_id"]
    PostgresRunStore(factory, "binh", conv, space_id=SP).save(_run("r1", ids["bao_cao_chi"]))
    org.add_message(conv, "USER", "Báo cáo của Chi thế nào?")
    org.add_message(conv, "ASSISTANT", "Chi chốt 120 đơn hàng.", run_id="r1")
    assert personal.get(conv) is None and personal.list() == []
    with pytest.raises(LookupError):
        personal.add_message(conv, "USER", "lách sang phạm vi cá nhân")
    assert org.get(conv)["messages"][1]["content"] == "Chi chốt 120 đơn hàng."
    with factory.begin() as s:
        s.get(OrgMemberRecord, (SP, "binh")).level = "STAFF"
    messages = org.get(conv)["messages"]
    assert messages[0]["content"] == "Báo cáo của Chi thế nào?"  # câu hỏi của chính mình vẫn còn
    assert messages[1]["content"] == REDACTED_ANSWER


# ---- API Studio

def _studio(factory, user_id, space_id=None, vectors=None):
    from app.storage.vector_store import InMemoryVectorStore

    def principal(request):
        return {"user_id": user_id, "role": "USER", "space_id": space_id}

    app = FastAPI()
    app.include_router(build_studio_router(
        current_user=principal, owner_pipeline=lambda user, *a: None, session_factory=lambda: factory,
        owner_source_store=lambda user: PostgresSourceStore(factory, user["user_id"], user.get("space_id")),
        vector_store=lambda: vectors or InMemoryVectorStore(),
    ))
    return TestClient(app)


def test_delete_respects_access_rules(world):
    factory, ids = world
    assert _studio(factory, "em", SP).delete(f"/api/studio/sources/{ids['noi_quy']}").status_code == 403  # thấy nhưng không được xóa
    assert _studio(factory, "em", SP).delete(f"/api/studio/sources/{ids['sap_nhap']}").status_code == 404  # không thấy
    assert _studio(factory, "chi").delete(f"/api/studio/sources/{ids['bang_gia']}").status_code == 404  # phạm vi cá nhân
    assert _studio(factory, "binh", SP).delete(f"/api/studio/sources/{ids['bang_gia']}").status_code == 200  # Trưởng phòng
    with factory() as s:
        assert s.get(KnowledgeSourceRecord, ids["bang_gia"]) is None
        assert s.get(KnowledgeSourceRecord, ids["noi_quy"]) is not None


def test_delete_removes_uploader_vectors(world):
    from app.storage.vector_store import InMemoryVectorStore, VectorRecord
    factory, ids = world
    vectors = InMemoryVectorStore(vector_size=2)
    vectors.upsert([VectorRecord(id=f"chi:{ids['bang_gia']}_c0000", vector=[1, 0], payload={"owner_user_id": "chi"})])
    assert _studio(factory, "an", SP, vectors).delete(f"/api/studio/sources/{ids['bang_gia']}").status_code == 200
    assert vectors.search([1, 0], owner_user_id="chi") == []  # mã vector mang tên người tải lên, không phải người xóa


def test_personal_only_routes_reject_org_scope(world):
    factory, _ = world
    assert _studio(factory, "chi", SP).get("/api/studio/workspaces").status_code == 400
    app = FastAPI()
    app.include_router(build_analysis_router(
        current_user=lambda request: {"user_id": "chi", "role": "USER", "space_id": SP},
        owner_pipeline=lambda user, *a: None, session_factory=lambda: factory,
    ))
    c = TestClient(app)
    assert c.post("/api/studio/reports", json={"kind": "mindmap", "title": "t", "payload": {}}).status_code == 400
    assert c.post("/api/studio/rating/studies", json={"title": "t", "items": [{"run_id": "r1"}]}).status_code == 400


class RecordingDb:
    def __init__(self): self.calls = []
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.calls.append(str(sql)); return self
    def mappings(self): return self
    def all(self): return []
    def scalar(self): return 0


def test_admin_table_masks_org_content():
    db = RecordingDb()
    app = FastAPI()
    app.include_router(build_studio_router(
        current_user=lambda request: {"user_id": "admin", "role": "ADMIN"},
        owner_pipeline=lambda user, *a: None, session_factory=lambda: (lambda: db),
    ))
    c = TestClient(app)
    for table, column in (("runs", "query"), ("conversations", "title"), ("knowledge_sources", "source_name")):
        db.calls.clear()
        assert c.get(f"/api/studio/admin/table/{table}", params={"q": "sáp nhập"}).status_code == 200
        select_sql, count_sql = db.calls
        masked = f"""CASE WHEN space_id IS NULL THEN CAST("{column}" AS TEXT) ELSE '{ORG_MASK}' END"""
        assert masked in select_sql and f'{masked}) AS "{column}"' in select_sql
        assert f'"{column}" AS TEXT) ILIKE' not in select_sql.replace(masked, "")  # tìm kiếm cũng không dò được
        assert masked in count_sql


def test_planning_pattern_ids_do_not_hide_answer(world):
    """21/11: mã src_… của kho mẫu lập kế hoạch không phải tài liệu; có trong lượt chạy cũng không được ẩn câu trả lời.
    Mã tài liệu thật không được phép thì vẫn ẩn như cũ."""
    from app.research.planning_retrieval import planning_source_ids
    factory, ids = world
    pattern_id = sorted(planning_source_ids())[0]
    store = PostgresRunStore(factory, "chi", space_id=SP)
    run = _run("r_plan", ids["bang_gia"])
    run["events"] = [{"stage": "planning_retrieval", "selected": [f"{pattern_id}_c0000"]}]
    store.save(run)
    assert store.get("r_plan")["answer"] == "câu trả lời có nội dung tài liệu"
    binh = PostgresRunStore(factory, "binh", space_id=SP)
    run2 = _run("r_plan_secret", ids["bang_gia"], ids["bao_cao_chi"])
    run2["events"] = [{"stage": "planning_retrieval", "selected": [f"{pattern_id}_c0000"]}]
    binh.save(run2)
    assert binh.get("r_plan_secret")["answer"] != REDACTED_ANSWER
    with factory.begin() as s:  # mất quyền với tài liệu thật thì vẫn ẩn
        s.get(OrgMemberRecord, (SP, "binh")).level = "STAFF"
    assert binh.get("r_plan_secret")["answer"] == REDACTED_ANSWER
