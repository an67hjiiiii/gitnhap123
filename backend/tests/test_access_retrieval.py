"""Đợt 3 phân quyền: test rò rỉ cho luồng AI.

Dùng đúng các thành phần thật của luồng truy xuất (PostgresSourceStore, CandidateIndex, ResearchPipeline._retrieve_candidates,
cả đường vector lẫn đường từ khóa dự phòng) trên SQLite cùng mô hình. Không gọi Ollama: kiểm tra phần quyết định
AI được NHÌN THẤY đoạn văn nào, vì mô hình chỉ có thể lộ những gì nó được đưa vào.
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.research.pipeline import ResearchPipeline
from app.retrieval.candidate_index import CandidateIndex
from app.storage.postgres.base import Base
from app.storage.postgres.models import (
    KnowledgeSourceRecord,
    OrgDepartmentRecord,
    OrgMemberRecord,
    OrgSpaceRecord,
    UserRecord,
)
from app.storage.postgres.runtime import PostgresSourceStore
from app.storage.vector_store import InMemoryVectorStore, QdrantVectorStore

SP = "sp_abc"
PEOPLE = ["an", "binh", "chi", "dung", "em", "ha", "giang"]
# mã: (người tải lên, phòng, mức mật, nội dung, câu hỏi nhắm đúng tài liệu)
DOCS = {
    "bang_gia": ("chi", "d_kd", "DEPARTMENT",
                 "Bảng giá sản phẩm máy lọc nước AquaPure: giá bán lẻ năm triệu đồng, chiết khấu đại lý mười phần trăm.",
                 "giá bán lẻ máy lọc nước AquaPure"),
    "bao_cao_chi": ("chi", "d_kd", "RESTRICTED",
                    "Báo cáo doanh số tháng mười một: chốt một trăm hai mươi đơn hàng với khách hàng Hoàng Long.",
                    "doanh số đơn hàng khách hàng Hoàng Long"),
    "danh_gia_ns": ("binh", "d_kd", "RESTRICTED",
                    "Đánh giá nhân sự phòng kinh doanh: xếp loại hiệu suất, đề xuất tăng lương và thưởng cuối năm.",
                    "đánh giá nhân sự đề xuất tăng lương thưởng"),
    "sap_nhap": ("an", None, "SECRET",
                 "Kế hoạch sáp nhập với công ty Minh Phát dự kiến hoàn tất quý hai, giá trị thương vụ năm mươi tỷ.",
                 "kế hoạch sáp nhập công ty Minh Phát thương vụ"),
    "noi_quy": ("an", None, "COMPANY",
                "Nội quy công ty: giờ làm việc bắt đầu tám giờ sáng, nghỉ trưa từ mười hai giờ, mặc đồng phục thứ hai.",
                "nội quy giờ làm việc nghỉ trưa đồng phục"),
    "nhap_chi": ("chi", "d_kd", "PRIVATE",
                 "Bản nháp ý tưởng chiến dịch quảng cáo mùa hè trên mạng xã hội TikTok cho học sinh sinh viên.",
                 "ý tưởng chiến dịch quảng cáo mùa hè TikTok"),
}
EXPECTED = {
    "an": {"bang_gia", "bao_cao_chi", "danh_gia_ns", "sap_nhap", "noi_quy"},
    "binh": {"bang_gia", "bao_cao_chi", "danh_gia_ns", "noi_quy"},
    "chi": {"bang_gia", "bao_cao_chi", "noi_quy", "nhap_chi"},
    "dung": {"noi_quy"},
    "em": {"noi_quy"},
    "ha": set(),
    "giang": set(),
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
    vectors = InMemoryVectorStore()
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
            OrgMemberRecord(space_id=SP, user_id="dung", department_id="d_kt", level="MANAGER", status="ACTIVE"),
            OrgMemberRecord(space_id=SP, user_id="em", department_id="d_kt", level="STAFF", status="ACTIVE"),
            OrgMemberRecord(space_id=SP, user_id="ha", level="STAFF", status="PENDING"),
        ])
    ids = {}
    # tải lên như hiện nay (cá nhân), lập chỉ mục vector, rồi mới nộp vào tổ chức với mức mật
    for code, (owner, dept, level, content, _) in DOCS.items():
        store = PostgresSourceStore(factory, owner)
        sid = store.import_text(f"{code}.txt", content)["source_id"]
        CandidateIndex(store, vectors, owner_user_id=owner).index_source(sid)
        ids[code] = sid
    personal = PostgresSourceStore(factory, "chi")
    ids["ca_nhan_chi"] = personal.import_text("ca_nhan.txt", "Ghi chú cá nhân của Chi về lịch học tiếng Anh buổi tối.")["source_id"]
    CandidateIndex(personal, vectors, owner_user_id="chi").index_source(ids["ca_nhan_chi"])
    with factory.begin() as s:
        for code, (_, dept, level, _, _) in DOCS.items():
            row = s.get(KnowledgeSourceRecord, ids[code])
            row.space_id, row.department_id, row.classification = SP, dept, level
    return factory, vectors, ids


def _retrieve(factory, vectors, user, query, space_id=SP, use_vector=True):
    store = PostgresSourceStore(factory, user, space_id)
    index = CandidateIndex(store, vectors, owner_user_id=user) if use_vector else None
    pipeline = ResearchPipeline(store, None, candidate_index=index)
    chunks = store.chunks(None)
    return {c.source_id for c in pipeline._retrieve_candidates(query, chunks, top_k=5, min_score=0.0, source_ids=None)}


@pytest.mark.parametrize("use_vector", [True, False], ids=["vector", "tu_khoa"])
@pytest.mark.parametrize("person", PEOPLE)
def test_no_leak_every_person_every_question(world, person, use_vector):
    factory, vectors, ids = world
    allowed = {ids[c] for c in EXPECTED[person]}
    for code, (*_, query) in DOCS.items():
        got = _retrieve(factory, vectors, person, query, use_vector=use_vector)
        assert got <= allowed, f"{person} hỏi về {code} nhận được tài liệu cấm"
        if code in EXPECTED[person]:
            assert ids[code] in got, f"{person} phải tìm thấy {code}"  # đối chứng: bộ lọc không chặn nhầm


def test_secret_question_from_staff_gets_nothing_secret(world):
    factory, vectors, ids = world
    query = DOCS["sap_nhap"][4]
    assert ids["sap_nhap"] in _retrieve(factory, vectors, "an", query)
    for person in ("binh", "chi", "dung", "em"):
        assert ids["sap_nhap"] not in _retrieve(factory, vectors, person, query)


def test_personal_scope_excludes_org_documents(world):
    factory, vectors, ids = world
    store = PostgresSourceStore(factory, "chi")  # phạm vi cá nhân
    assert {c.source_id for c in store.chunks(None)} == {ids["ca_nhan_chi"]}
    assert {s["source_id"] for s in store.list_sources()} == {ids["ca_nhan_chi"]}
    got = _retrieve(factory, vectors, "chi", DOCS["bang_gia"][4], space_id=None)
    assert got <= {ids["ca_nhan_chi"]}
    # tài liệu cá nhân không lọt vào phạm vi tổ chức
    assert ids["ca_nhan_chi"] not in _retrieve(factory, vectors, "chi", "lịch học tiếng Anh buổi tối")


def test_removed_member_loses_ai_access_immediately(world):
    factory, vectors, ids = world
    query = DOCS["danh_gia_ns"][4]
    assert ids["danh_gia_ns"] in _retrieve(factory, vectors, "binh", query)
    with factory.begin() as s:
        s.delete(s.get(OrgMemberRecord, (SP, "binh")))
    assert _retrieve(factory, vectors, "binh", query) == set()
    assert _retrieve(factory, vectors, "binh", query, space_id=None) == set()  # không lách qua phạm vi cá nhân
    store = PostgresSourceStore(factory, "binh", SP)
    assert store.chunks(None) == [] and store.source(ids["danh_gia_ns"]) is None


def test_store_reads_respect_scope(world):
    factory, _, ids = world
    em = PostgresSourceStore(factory, "em", SP)
    assert em.source(ids["sap_nhap"]) is None
    assert em.source_status(ids["bang_gia"]) is None
    assert em.chunk(f"{ids['sap_nhap']}_c0000") is None
    assert em.chunks([ids["sap_nhap"]]) == []
    with pytest.raises(LookupError):
        em.validate_source_selection([ids["sap_nhap"]])
    em.validate_source_selection([ids["noi_quy"]])
    assert em.source(ids["noi_quy"]) is not None


def test_selecting_forbidden_source_returns_nothing(world):
    factory, vectors, ids = world
    store = PostgresSourceStore(factory, "chi", SP)
    index = CandidateIndex(store, vectors, owner_user_id="chi")
    assert index.candidates("sáp nhập Minh Phát", source_ids=[ids["sap_nhap"]]) == []
    assert index.candidates("sáp nhập Minh Phát", source_ids=[]) == []


def test_clear_only_removes_personal_documents(world):
    factory, _, ids = world
    PostgresSourceStore(factory, "chi").clear()
    with factory() as s:
        assert s.get(KnowledgeSourceRecord, ids["ca_nhan_chi"]) is None
        assert s.get(KnowledgeSourceRecord, ids["bang_gia"]) is not None


@pytest.fixture()
def qdrant(tmp_path):
    from app.storage.vector_store import VectorRecord
    store = QdrantVectorStore(path=str(tmp_path / "q"), collection="t", vector_size=3)
    store.upsert([VectorRecord(id="a:1", vector=[1, 0, 0], payload={"owner_user_id": "a", "source_id": "s1", "chunk_id": "1"}),
                  VectorRecord(id="b:2", vector=[1, 0, 0], payload={"owner_user_id": "b", "source_id": "s2", "chunk_id": "2"})])
    yield store
    store.client.close()


@pytest.mark.parametrize("backend", ["memory", "qdrant"])
def test_vector_store_fails_closed(backend, request):
    if backend == "memory":
        from app.storage.vector_store import VectorRecord
        store = InMemoryVectorStore(vector_size=3)
        store.upsert([VectorRecord(id="a:1", vector=[1, 0, 0], payload={"owner_user_id": "a", "source_id": "s1"}),
                      VectorRecord(id="b:2", vector=[1, 0, 0], payload={"owner_user_id": "b", "source_id": "s2"})])
    else:
        store = request.getfixturevalue("qdrant")
    assert store.search([1, 0, 0], owner_user_id="a", source_ids=[]) == []  # rỗng = không tìm
    assert store.search([1, 0, 0], source_ids=[]) == []
    with pytest.raises(ValueError):
        store.search([1, 0, 0])  # không có phạm vi thì từ chối
    assert {m.payload["source_id"] for m in store.search([1, 0, 0], source_ids=["s2"])} == {"s2"}
    assert {m.payload["source_id"] for m in store.search([1, 0, 0], owner_user_id="a")} == {"s1"}
