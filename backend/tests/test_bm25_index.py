"""Persistent BM25 lifecycle, Vietnamese fields, legacy parity and scoped reads."""
from dataclasses import replace
import os
from types import SimpleNamespace

import pytest

from app.retrieval import bm25_index as bm
from app.retrieval.candidate_index import cached_rank
from app.storage.source_store import SourceStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("BM25_INDEX", "persist")
    monkeypatch.delenv("BM25_INDEX_DIR", raising=False)
    bm._PERSISTED.clear()
    return SourceStore(str(tmp_path))


def search(store, query="mat khau toi thieu", source_ids=None):
    return cached_rank(store, query, source_ids, 10, bm25=True)


def test_ingestion_build_once_queries_only_load(store, monkeypatch):
    builds = []
    original = bm.rebuild
    def counted(*args, **kwargs):
        builds.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(bm, "rebuild", counted)
    source = store.import_text("security.md", "Mật khẩu tối thiểu phải có 12 ký tự.")["source_id"]
    assert builds == [1]
    # Simulate a restart. Even the first query loads the saved postings verbatim.
    bm._PERSISTED.clear()
    monkeypatch.setattr(store, "chunks", lambda *args: pytest.fail("query loaded full corpus"))
    monkeypatch.setattr(bm.PersistentIndex, "replace_sources", lambda *args: pytest.fail("query built index"))
    for _ in range(3):
        assert search(store)[0].source_id == source
    assert builds == [1]
    assert bm.index_path(store).exists()


def test_incremental_add_replace_delete(store, monkeypatch):
    old = store.import_text("security.md", "Mật khẩu cũ có 6 ký tự.")["source_id"]
    monkeypatch.setattr(bm, "rebuild", lambda *args: pytest.fail("incremental ingestion rebuilt corpus"))
    reads = []
    original = store.chunks
    def chunks(ids=None):
        reads.append(ids)
        assert ids is not None
        return original(ids)
    monkeypatch.setattr(store, "chunks", chunks)
    new = store.import_text("security.md", "Mật khẩu tối thiểu có 12 ký tự.")["source_id"]
    other = store.import_text("backup.md", "Bản sao lưu được giữ 30 ngày.")["source_id"]
    assert reads == [[new], [other]]
    assert search(store)[0].source_id == new
    index = bm._PERSISTED[bm.index_path(store)][1]
    assert old not in {doc["source"] for doc in index.documents.values()}
    # Same-source chunk deletion uses the same incremental API.
    previous = bm.signature(store)
    store._chunks = [c for c in store._chunks if c.source_id != new]
    store._save()
    bm.update_source(store, new, previous)
    assert search(store) == []


def test_folded_field_and_weight(store):
    target = store.import_text("security.md", "Mật khẩu tối thiểu phải có 12 ký tự.")["source_id"]
    store.import_text("backup.md", "Sao lưu dữ liệu mỗi ngày.")
    assert search(store)[0].source_id == target
    assert bm.fold_text("ĐẶT MẬT KHẨU") == "dat mat khau"
    index = bm._PERSISTED[bm.index_path(store)][1]
    assert bm.FOLDED_FIELD_WEIGHT == 0.5
    accented = index.rank("mật khẩu", [target], 1)[0][1]
    folded = index.rank("mat khau", [target], 1)[0][1]
    assert accented == pytest.approx(3 * folded, abs=0.000003)


def test_unique_tokenizer_bigram_fallback(monkeypatch):
    monkeypatch.setattr(bm, "_segment", None)
    assert bm.tokenize("Mật khẩu tối thiểu.") == [
        "mật", "khẩu", "tối", "thiểu", "mật_khẩu", "khẩu_tối", "tối_thiểu"]
    assert "khẩu_tối" not in bm.tokenize("mật khẩu. tối thiểu")


def test_signature_mismatch_repairs_once(store, monkeypatch):
    store.import_text("security.md", "Mật khẩu tối thiểu có 12 ký tự.")
    store._chunks = [replace(c, text="Mật khẩu tối thiểu có 20 ký tự.") for c in store._chunks]
    store._save()  # external/legacy write bypassed incremental hook
    calls = []
    original = bm.rebuild
    def rebuild(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(bm, "rebuild", rebuild)
    for _ in range(3):
        assert "20" in search(store)[0].text
    assert calls == [1]


def test_corrupt_file_repairs_once(store, monkeypatch):
    store.import_text("security.md", "Mật khẩu tối thiểu có 12 ký tự.")
    bm.index_path(store).write_bytes(b"invalid gzip")
    bm._PERSISTED.clear()
    assert search(store)
    monkeypatch.setattr(bm, "rebuild", lambda *args: pytest.fail("rebuilt twice"))
    assert search(store)


def test_flag_off_legacy_parity(store, monkeypatch):
    from app.retrieval.hybrid import bm25_rank
    store.import_text("security.md", "Mật khẩu tối thiểu có 12 ký tự.")
    monkeypatch.delenv("BM25_INDEX", raising=False)
    monkeypatch.delenv("RETRIEVAL_NO_FULL_LOAD", raising=False)
    assert search(store) is None
    rows = store.chunks()
    expected = [(c.chunk_id, c.score) for c in bm25_rank("mật khẩu", rows)]
    monkeypatch.setenv("RETRIEVAL_NO_FULL_LOAD", "1")
    assert search(store, "mật khẩu") is None  # file store keeps its original R2 fallback
    assert [(c.chunk_id, c.score) for c in bm25_rank("mật khẩu", rows)] == expected


def test_pipeline_fusion_uses_persist_without_r2(store, monkeypatch):
    from app.research.pipeline import ResearchPipeline
    from app.research.product_retrieval import _lists_for
    store.import_text("security.md", "Mật khẩu tối thiểu có 12 ký tự.")
    monkeypatch.delenv("RETRIEVAL_NO_FULL_LOAD", raising=False)
    monkeypatch.setattr(store, "chunks", lambda *args: pytest.fail("full load in pipeline"))
    groups = _lists_for(ResearchPipeline(store, None), "mat khau toi thieu", None,
                        SimpleNamespace(retrieval_min_score=0.0), None, 10, "bm25")
    assert groups[1]


def test_effective_scope_precedes_statistics_and_hydration(store, monkeypatch):
    allowed = store.import_text("public.md", "Mật khẩu tối thiểu có 12 ký tự.")["source_id"]
    secret = store.import_text("private.md", "Mật khẩu tối thiểu bí mật có 90 ký tự.")["source_id"]
    monkeypatch.setattr(store, "effective_source_ids", lambda q, ids: {allowed} & (
        {allowed} if ids is None else set(ids)), raising=False)
    rows = search(store)
    assert rows and {c.source_id for c in rows} == {allowed}
    assert search(store, source_ids=[secret]) == []
    reference = bm.PersistentIndex()
    reference.replace_sources(set(), store.chunks([allowed]))
    assert [(c.chunk_id, c.score) for c in rows] == reference.rank("mat khau toi thieu", None, 10)


def test_paths_isolate_owner_space_and_explicit_rebuild(store, tmp_path):
    store.import_text("security.md", "Mật khẩu tối thiểu có 12 ký tự.")
    path = bm.index_path(store)
    store.owner_user_id = "../other"
    assert bm.index_path(store) != path
    owner_path = bm.index_path(store)
    store.space_id = "space"
    assert bm.index_path(store) != owner_path
    directory = tmp_path / "manual"
    assert bm.rebuild(store, directory).documents
    assert bm.index_path(store, directory).exists()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="scratch PostgreSQL required")
def test_postgres_incremental_restart_signature_and_acl(store, monkeypatch, tmp_path):
    from uuid import uuid4
    from sqlalchemy import create_engine, delete, update
    from sqlalchemy.orm import sessionmaker
    from app.storage.postgres.models import KnowledgeSourceRecord, UserRecord
    from app.storage.postgres.runtime import PostgresSourceStore

    monkeypatch.setenv("BM25_INDEX_DIR", str(tmp_path / "indexes"))
    monkeypatch.setenv("VERSION_PROPOSE", "0")
    monkeypatch.setenv("VERSION_DIFF", "0")
    monkeypatch.setenv("VERSION_FILTER", "off")
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = sessionmaker(engine)
    owners = ["bm25_" + uuid4().hex for _ in range(2)]
    try:
        with factory.begin() as db:
            for owner in owners:
                db.add(UserRecord(user_id=owner, username=owner, display_name="BM25", password_hash="test"))
        current = PostgresSourceStore(factory, owners[0])
        other = PostgresSourceStore(factory, owners[1])
        public = current.import_text("security.md", "Mật khẩu tối thiểu có 12 ký tự.")["source_id"]
        private = other.import_text("private.md", "Mật khẩu tối thiểu bí mật có 90 ký tự.")["source_id"]
        calls = []
        original = PostgresSourceStore.chunks
        def chunks(self, source_ids=None):
            calls.append(source_ids)
            return original(self, source_ids)
        monkeypatch.setattr(PostgresSourceStore, "chunks", chunks)
        added = current.import_text("backup.md", "Sao lưu mật khẩu mỗi ngày.")["source_id"]
        assert calls == [[added]]
        bm._PERSISTED.clear()
        for _ in range(3):
            request = PostgresSourceStore(factory, owners[0])
            assert search(request)[0].source_id == public
            assert search(request, source_ids=[private]) == []
        assert calls == [[added]]  # restart and repeated requests never load/build
        # Transfer ownership with unchanged total database row count: scope signature changes.
        with factory.begin() as db:
            db.execute(update(KnowledgeSourceRecord).where(KnowledgeSourceRecord.source_id == public)
                       .values(owner_user_id=owners[1]))
        for _ in range(3):
            assert all(c.source_id != public for c in search(current))
        assert calls == [[added], None]  # exactly one repair on scope mismatch
    finally:
        with factory.begin() as db:
            db.execute(delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.owner_user_id.in_(owners)))
            db.execute(delete(UserRecord).where(UserRecord.user_id.in_(owners)))
        engine.dispose()
