"""S6 persistence, S4 endpoint isolation, and retrieval-free quick answers."""
import asyncio
import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.types import ProviderResult, RunMetrics
from app.ingestion.documents import extract_document
from app.research.pipeline import ResearchPipeline
from app.research.vanilla import answer_vanilla
from app.storage.postgres.models import (DocumentVersionRecord, KnowledgeSourceRecord,
    OrgSpaceRecord, OrgMemberRecord, UserRecord, VersionDiffRecord)
from app.storage.postgres.runtime import PostgresSourceStore
from app.storage.run_store import RunStore

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
DATA = Path(os.getenv("S6_TEST_DATA", "D:/CAP1-Orchestration/work/version_test"))


@pytest.fixture
def version_db(monkeypatch):
    monkeypatch.setenv("VERSION_DIFF", "1")
    monkeypatch.setenv("VERSION_PROPOSE", "1")
    monkeypatch.setenv("VERSION_FILTER", "on")
    monkeypatch.setenv("CHUNK_MODE", "legal")
    monkeypatch.setenv("INGEST_CLEAN", "rules")
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = sessionmaker(engine)
    owners = ["s6_" + uuid4().hex for _ in range(2)]
    space = "s6_" + uuid4().hex
    with factory.begin() as db:
        for owner in owners:
            db.add(UserRecord(user_id=owner, username=owner, display_name="S6", password_hash="test-only"))
    stores = [PostgresSourceStore(factory, o) for o in owners]
    ids = {}
    try:
        for policy in ("CS_DANGNHAP", "CS_NHATKY", "CS_API"):
            for v in (1, 2):
                name = f"{policy}_v{v}.txt"
                text = extract_document((DATA / name).read_bytes(), name).text
                ids[policy, v] = stores[0].import_text(name, text)["source_id"]
        yield factory, stores, ids, space
    finally:
        with factory.begin() as db:
            db.execute(delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.owner_user_id.in_(owners)))
            db.execute(delete(OrgMemberRecord).where(OrgMemberRecord.space_id == space))
            db.execute(delete(OrgSpaceRecord).where(OrgSpaceRecord.space_id == space))
            db.execute(delete(UserRecord).where(UserRecord.user_id.in_(owners)))
        engine.dispose()


def stored(factory, store):
    with factory() as db:
        ids = select(KnowledgeSourceRecord.source_id).where(KnowledgeSourceRecord.owner_user_id == store.owner_user_id)
        return db.scalars(select(VersionDiffRecord).where(VersionDiffRecord.new_source_id.in_(ids))).all()


def test_save_reimport_confirm_recompute_and_off(version_db, monkeypatch):
    factory, (store, stranger), ids, _ = version_db
    assert len(stored(factory, store)) == 12
    sid = ids["CS_API", 2]
    store.confirm_version(sid, store.owner_user_id)
    store.confirm_version(sid, store.owner_user_id)
    assert len(stored(factory, store)) == 12
    assert stranger.version_diff_evidence("So sánh chính sách API") is None
    # A version moved to a different family removes stale edges on confirmation.
    with factory.begin() as db:
        v = db.scalar(select(DocumentVersionRecord).where(DocumentVersionRecord.source_id == sid))
        v.family_key = "ISOLATED"
    store.confirm_version(sid, store.owner_user_id)
    assert len(stored(factory, store)) == 9
    monkeypatch.setenv("VERSION_DIFF", "0")
    monkeypatch.setenv("VERSION_PROPOSE", "0")
    monkeypatch.setattr(store, "_refresh_version_diffs", lambda *a: pytest.fail("diff called while off"))
    assert store.version_diff_evidence("So sánh chính sách") is None
    store.import_text("off.txt", "Điều 1. Nội dung\nPhải chờ 30 phút.")
    assert len(stored(factory, store)) == 9


def test_policy_kind_and_unchanged_evidence(version_db):
    _, (store, _), ids, _ = version_db
    assert len(store.version_diff_evidence("So sánh chính sách đăng nhập")) == 6
    assert len(store.version_diff_evidence("So sánh chính sách nhật ký")) == 3
    assert len(store.version_diff_evidence("So sánh chính sách API")) == 3
    removed = store.version_diff_evidence("Chính sách nhật ký có mục nào bị bỏ?")
    assert len(removed) == 1 and "Loại: BO" in removed[0].text
    added = store.version_diff_evidence("Điểm mới của chính sách API")
    assert len(added) == 1 and "Retry-After" in added[0].text
    general_new = store.version_diff_evidence("Chính sách API có gì mới?")
    assert len(general_new) == 3
    for query in ("Thời gian mở khóa có thay đổi không?", "Thời hạn API key có thay đổi không?",
                  "Sao lưu nhật ký có thay đổi không?"):
        evidence = store.version_diff_evidence(query)
        assert len(evidence) == 2, query
        assert all(c.provenance.get("version_unchanged") for c in evidence)
        assert len({c.source_id for c in evidence}) == 2
    assert store.version_diff_evidence("Mật khẩu dài bao nhiêu?") is None
    assert store.version_diff_evidence("So sánh chính sách API", []) is None
    assert store.version_diff_evidence("So sánh chính sách API", [ids["CS_API", 2]]) is None


def test_out_of_order_adjacency_and_idempotent_import(version_db):
    factory, (store, _), ids, _ = version_db
    new_id = ids["CS_API", 2]
    with factory() as db:
        source = db.get(KnowledgeSourceRecord, new_id)
        text = source.display_metadata["_version_diff_text"]
    store.import_text("CS_API_v2.txt", text)
    assert len(stored(factory, store)) == 12
    middle = text.replace("Phiên bản: 2.0", "Phiên bản: 1.5").replace("01/10/2026", "01/01/2026")
    mid_id = store.import_text("CS_API_v15.txt", middle)["source_id"]
    rows = [r for r in stored(factory, store) if r.family_key == "CS-API-03"]
    assert len(rows) == 3
    assert {r.old_source_id for r in rows} == {ids["CS_API", 1]}
    assert {r.new_source_id for r in rows} == {mid_id}


def test_both_endpoints_require_s4_access(version_db):
    factory, (owner, reader), ids, space = version_db
    with factory.begin() as db:
        db.add(OrgSpaceRecord(space_id=space, name="S6"))
        db.flush()
        for store in (owner, reader):
            db.add(OrgMemberRecord(space_id=space, user_id=store.owner_user_id, level="EXECUTIVE", status="ACTIVE"))
        for v in (1, 2):
            source = db.get(KnowledgeSourceRecord, ids["CS_API", v])
            source.space_id = space
            source.classification = "COMPANY" if v == 2 else "PRIVATE"
    scoped = PostgresSourceStore(factory, reader.owner_user_id, space_id=space)
    assert scoped.version_diff_evidence("So sánh chính sách API") is None
    with factory.begin() as db:
        db.get(KnowledgeSourceRecord, ids["CS_API", 1]).classification = "COMPANY"
    assert len(scoped.version_diff_evidence("So sánh chính sách API")) == 3
    with factory.begin() as db:
        db.get(OrgMemberRecord, (space, reader.owner_user_id)).status = "PENDING"
    assert scoped.version_diff_evidence("So sánh chính sách API") is None


def test_quick_path_skips_retrieval_and_preserves_guard(version_db, monkeypatch, tmp_path, sf1_fake_provider_env):
    _, (store, _), _, _ = version_db
    from app.research import pipeline as module
    from app.chat.answer_guard import GuardResult
    evidence = store.version_diff_evidence("So sánh chính sách API")
    class Provider:
        name, model = "fake", "s6"
        async def generate(self, *, system, user):
            assert "MỘT câu" in system and "Trước:" in user and "Sau:" in user
            return ProviderResult(json.dumps({"status": "COMPLETE", "answer": "Giới hạn tăng từ 100 lên 300 yêu cầu mỗi phút.",
                "citations": [c.chunk_id for c in evidence]}, ensure_ascii=False))
    class Checker:
        called = False
        def guard(self, answer, **kwargs):
            self.called = True
            assert len(kwargs["evidence_texts"]) == 3
            assert any("100" in text and "300" in text for text in kwargs["evidence_texts"])
            return GuardResult(answer)
        def needs_verification(self, *args):
            return False
    checker = Checker()
    monkeypatch.setattr(module, "get_provider", lambda _: Provider())
    monkeypatch.setattr(module, "gpu_memory_mb", lambda: None)
    pipeline = ResearchPipeline(store, RunStore(str(tmp_path / "runs")))
    monkeypatch.setattr(pipeline, "_retrieve_candidates", lambda *a, **k: pytest.fail("retrieved instead of reading diff"))
    monkeypatch.setattr(module, "product_retrieve", lambda *a, **k: pytest.fail("product retrieval used"))
    result = asyncio.run(pipeline.run("So sánh chính sách API", "A", product_mode=True, answer_checker=checker))
    assert checker.called
    assert "100" in result["answer"] and "300" in result["answer"]


def test_unchanged_prompt_and_two_citations(version_db):
    _, (store, _), _, _ = version_db
    evidence = store.version_diff_evidence("Thời hạn API key có thay đổi không?")
    class Provider:
        async def generate(self, *, system, user):
            assert "không đổi về nội dung" in user
            assert "12 tháng" in user and "một năm" in user
            return ProviderResult(json.dumps({"status": "COMPLETE", "answer": "Thời hạn API key không đổi về nội dung.",
                "citations": [c.chunk_id for c in evidence]}, ensure_ascii=False))
    result = asyncio.run(answer_vanilla(Provider(), "Thời hạn API key có thay đổi không?", evidence, RunMetrics()))
    assert "không đổi về nội dung" in result.answer and len(result.citations) == 2
