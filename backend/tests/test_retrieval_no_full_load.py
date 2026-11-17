"""Retrieval load counters and scoped ranking parity; no model services."""
from concurrent.futures import ThreadPoolExecutor
import os
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.types import SourceChunk
from app.research.pipeline import ResearchPipeline
from app.research.product_retrieval import _lists_for
from app.retrieval.hybrid import bm25_rank
from app.retrieval.text import retrieve


class CountingStore:
    owner_user_id = "owner"
    space_id = "space"

    def __init__(self):
        self.rows = [SourceChunk(f"c{i:03}", f"s{i % 3}", "policy", text, i,
                                provenance={"context_header": "Policy access"})
                     for i, text in enumerate(["access expires after 45 minutes", "access policy limits",
                                               "backup archive retained 30 days"] * 20)]
        self.allowed = {"s0", "s1", "s2"}
        self.revision = 1
        self.loads = self.loaded = self.hydrated = 0

    def effective_source_ids(self, query, selected=None):
        return self.allowed if selected is None else self.allowed & set(selected)

    def retrieval_signature(self):
        return len(self.rows), self.revision, tuple(sorted(self.allowed))

    def chunks(self, source_ids=None):
        rows = [c for c in self.rows if c.source_id in self.effective_source_ids("", source_ids)]
        self.loads += 1
        self.loaded += len(rows)
        return rows

    def chunks_by_ids(self, ids, source_ids=None):
        rows = [c for c in self.rows if c.chunk_id in ids
                and c.source_id in self.effective_source_ids("", source_ids)]
        self.hydrated += len(rows)
        return rows


class Hits:
    def __init__(self, empty=False):
        self.empty = empty

    def candidates(self, query, **kwargs):
        if self.empty:
            return []
        return [SimpleNamespace(payload={"chunk_id": "c000"}, score=0.8)]


CFG = SimpleNamespace(task_top_k=4, retrieval_min_score=0.0)


def pairs(rows):
    return [(c.chunk_id, c.score) for c in rows]


@pytest.mark.parametrize("vector", [None, Hits(), Hits(empty=True)])
def test_second_query_does_not_load_corpus(monkeypatch, vector):
    monkeypatch.setenv("RETRIEVAL_NO_FULL_LOAD", "1")
    store = CountingStore()
    pipeline = ResearchPipeline(store, None, candidate_index=vector)
    first = _lists_for(pipeline, "access policy", None, CFG, None, 4, "hybrid")
    loads, loaded, hydrated = store.loads, store.loaded, store.hydrated
    second = _lists_for(pipeline, "access policy", None, CFG, None, 4, "hybrid")
    print(f"vector={vector is not None}: full_loads={loads}->{store.loads}, "
          f"rows={loaded}->{store.loaded}, hydrated={hydrated}->{store.hydrated}")
    assert store.loads == loads == 1
    assert store.loaded == loaded == len(store.rows)
    assert [pairs(x) for x in second] == [pairs(x) for x in first]


def test_bm25_and_lexical_equal_legacy_for_effective_scope(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_NO_FULL_LOAD", "1")
    store = CountingStore()
    pipeline = ResearchPipeline(store, None, candidate_index=Hits())
    for selected in (None, [], ["s0"], ["s1", "s2"], ["foreign", "s0"]):
        for query in ("access", "archive retained", "unknown", "access backup"):
            groups = _lists_for(pipeline, query, None, CFG, selected, 20, "hybrid")
            rows = [c for c in store.rows if c.source_id in store.effective_source_ids(query, selected)]
            assert pairs(groups[1]) == pairs(bm25_rank(query, rows, 20))
            assert pairs(groups[3]) == pairs(retrieve(query, rows, 20, 0.0))
    assert store.loads == 1
    store.allowed = {"s2"}  # ACL changes with the same owner and space.
    groups = _lists_for(pipeline, "archive", None, CFG, None, 20, "hybrid")
    assert all(c.source_id == "s2" for group in groups for c in group)


def test_refresh_and_concurrent_cache_build(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_NO_FULL_LOAD", "1")
    store = CountingStore()
    pipeline = ResearchPipeline(store, None)
    def search(_):
        return _lists_for(pipeline, "access", None, CFG, None, 4, "bm25")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(search, range(8)))
    assert store.loads == 1
    store.rows[0] = replace(store.rows[0], text="access revised policy")
    store.revision += 1
    search(0)
    assert store.loads == 2


def test_flag_off_retains_legacy_loads(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_NO_FULL_LOAD", raising=False)
    store = CountingStore()
    pipeline = ResearchPipeline(store, None)
    for _ in range(2):
        _lists_for(pipeline, "access", None, CFG, None, 4, "bm25")
    assert store.loads == 4  # lexical plus fusion, as before.


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="scratch PostgreSQL required")
def test_postgres_snapshot_hydration_and_cross_request_cache(monkeypatch):
    from sqlalchemy import create_engine, delete, event, update
    from sqlalchemy.orm import sessionmaker
    from app.storage.postgres.models import KnowledgeSourceRecord, UserRecord
    from app.storage.postgres.runtime import PostgresSourceStore

    monkeypatch.setenv("RETRIEVAL_NO_FULL_LOAD", "1")
    monkeypatch.setenv("VERSION_FILTER", "off")
    monkeypatch.setenv("VERSION_DIFF", "0")
    monkeypatch.setenv("VERSION_PROPOSE", "0")
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = sessionmaker(engine)
    owner = "r2_" + uuid4().hex
    queries = []
    def record(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)
    event.listen(engine, "before_cursor_execute", record)
    try:
        with factory.begin() as db:
            db.add(UserRecord(user_id=owner, username=owner, display_name="R2", password_hash="test"))
        store = PostgresSourceStore(factory, owner)
        source = store.import_text("policy.md", "\n\n".join(
            f"# Section {i}\nAccess expires after {i + 10} minutes." for i in range(30)))["source_id"]
        canonical = store.chunks()
        loads = []
        original = PostgresSourceStore.chunks
        def counted(self, *args, **kwargs):
            rows = original(self, *args, **kwargs)
            loads.append(len(rows))
            return rows
        monkeypatch.setattr(PostgresSourceStore, "chunks", counted)
        snapshot = store.snapshot_id()
        queries.clear()
        rows = store.chunks_by_ids([canonical[0].chunk_id], [source])
        chunk_reads = [q for q in queries if "FROM knowledge_chunks" in q]
        assert len(rows) == len(chunk_reads) == 1
        assert "knowledge_chunks.chunk_id IN" in chunk_reads[0]
        assert not loads  # snapshot and vector hydration never load the corpus.
        for request in range(2):
            current = PostgresSourceStore(factory, owner)
            assert current.snapshot_id() == snapshot
            groups = _lists_for(ResearchPipeline(current, None), "access minutes", None,
                                CFG, [source], 4, "bm25")
            assert pairs(groups[1]) == pairs(bm25_rank("access minutes", canonical, 4))
        assert loads == [len(canonical)]
        with factory.begin() as db:
            db.execute(update(KnowledgeSourceRecord).where(KnowledgeSourceRecord.source_id == source)
                       .values(source_name="renamed.md"))
        assert store.snapshot_id() != snapshot
        _lists_for(ResearchPipeline(store, None), "access", None, CFG, [source], 4, "bm25")
        assert loads == [len(canonical), len(canonical)]
    finally:
        event.remove(engine, "before_cursor_execute", record)
        with factory.begin() as db:
            db.execute(delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.owner_user_id == owner))
            db.execute(delete(UserRecord).where(UserRecord.user_id == owner))
        engine.dispose()
