"""3 users x 9 documents x 3 intents x 2 flags against the scratch PostgreSQL DB."""
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.access import visible_source_ids
from app.research.pipeline import ResearchPipeline
from app.retrieval.candidate_index import CandidateIndex
from app.storage.postgres.models import (DocumentVersionRecord, KnowledgeSourceRecord,
    OrgSpaceRecord, OrgDepartmentRecord, OrgMemberRecord, OrgSourceShareRecord, UserRecord)
from app.storage.postgres.runtime import PostgresSourceStore
from app.storage.vector_store import InMemoryVectorStore

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set")
MATRIX = Path(r"D:\CAP1-Orchestration\work\p3\s4\leak_matrix.json")
CORPUS = Path(r"D:\CAP1-Orchestration\work\legal_corpus\demo_zips\Demo Phan Quyen\tai-lieu")


class DeterministicEmbedder:
    dimension = 2
    version = "s4-deterministic-v1"
    def embed(self, text):
        return (1.0, 0.0)
    def embed_many(self, texts):
        return [self.embed(t) for t in texts]


@pytest.fixture
def matrix_db(monkeypatch):
    monkeypatch.setenv("VERSION_PROPOSE", "0")
    monkeypatch.setenv("VERSION_FILTER", "off")
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = sessionmaker(engine)
    prefix = "s4_" + uuid4().hex[:12]
    space, dept = prefix + "space", prefix + "dept"
    users = {name: prefix + name for name in matrix["users"]}
    vectors = InMemoryVectorStore(vector_size=2)
    ids = {}
    try:
        with factory.begin() as db:
            for uid in users.values():
                db.add(UserRecord(user_id=uid, username=uid, display_name="S4", password_hash="test-only"))
            db.flush()
            db.add(OrgSpaceRecord(space_id=space, name=prefix))
            db.flush()
            db.add(OrgDepartmentRecord(department_id=dept, space_id=space, name="Kinh doanh"))
            db.flush()
            for name, info in matrix["users"].items():
                db.add(OrgMemberRecord(space_id=space, user_id=users[name],
                    level="EXECUTIVE" if info["level"] == "OWNER_BOARD" else info["level"],
                    department_id=dept if info["department"] else None, status="ACTIVE"))
        # Index while sources are personal, then move metadata to the organization.
        for doc in matrix["docs"]:
            key = doc["key"]
            if key == "quyche_draft":
                text = "Quy chế thưởng (dự thảo) thưởng Tết 2 tháng lương"
            else:
                number = doc["file"][:2]
                path = next(CORPUS.glob(number + "_*.md"))
                text = path.read_text(encoding="utf-8")
                if key == "noiquy_v2":
                    text += "\nSửa đổi: Giờ làm 8h30 sáng."
                elif key == "banggia_v2":
                    text += "\nSửa đổi: AquaPure X2 giá 7.200.000 đ."
            store = PostgresSourceStore(factory, users[doc["uploader"]])
            source = store.import_text(key + ".md", text)["source_id"]
            ids[key] = source
            CandidateIndex(store, vectors, owner_user_id=store.owner_user_id,
                           embedder=DeterministicEmbedder()).index_source(source)
            with factory.begin() as db:
                row = db.get(KnowledgeSourceRecord, source)
                row.space_id, row.department_id = space, dept if doc["department"] else None
                row.classification = doc["classification"]
                if doc["family"]:
                    db.add(DocumentVersionRecord(id=prefix + key, source_id=source,
                        owner_user_id=store.owner_user_id, family_key=doc["family"],
                        version_label=doc["version"], status=doc["version_status"],
                        effective_from=date.fromisoformat(doc["effective_from"]),
                        confirmed_by=store.owner_user_id, confirmed_at=datetime.now(timezone.utc)))
        yield matrix, factory, users, space, dept, ids, vectors
    finally:
        with factory.begin() as db:
            db.execute(delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.owner_user_id.in_(users.values())))
            db.execute(delete(OrgMemberRecord).where(OrgMemberRecord.space_id == space))
            db.execute(delete(OrgSpaceRecord).where(OrgSpaceRecord.space_id == space))
            db.execute(delete(UserRecord).where(UserRecord.user_id.in_(users.values())))
        engine.dispose()


def test_leak_matrix(matrix_db, monkeypatch):
    matrix, factory, users, space, _, ids, vectors = matrix_db
    leaks = mismatches = checks = 0
    for name, uid in users.items():
        store = PostgresSourceStore(factory, uid, space_id=space)
        index = CandidateIndex(store, vectors, owner_user_id=uid, embedder=DeterministicEmbedder())
        pipeline = ResearchPipeline(store, None, candidate_index=index)
        visible = {ids[k] for k in matrix["visible_expected"][name]}
        with factory() as db:
            assert visible_source_ids(db, uid, space) == visible
        for flag in ("off", "on"):
            monkeypatch.setenv("VERSION_FILTER", flag)
            for intent, query in (("current", "Quy định hiện hành"), ("old", "bản cũ"), ("draft", "dự thảo")):
                expected = ({ids[k] for k in matrix["version_filter_on_current_query_expected"][name]}
                            if flag == "on" and intent == "current" else visible)
                row_leaks = row_mismatches = 0
                # None, explicit empty, all, singletons, and mixed authorized/unauthorized selections.
                selections = [None, [], list(ids.values()), *[[sid] for sid in ids.values()],
                              [ids["noiquy_v1"], ids["sapnhap"]]]
                for selected in selections:
                    wanted = expected if selected is None else expected & set(selected)
                    effective = store.effective_source_ids(query, selected)
                    raw = index.candidates(query, limit=100, source_ids=selected)
                    raw_ids = {m.payload["source_id"] for m in raw}
                    chunks = pipeline._retrieve_candidates(query, None, top_k=100, min_score=-1, source_ids=selected)
                    actual = {c.source_id for c in chunks}
                    row_leaks += len((effective | raw_ids | actual) - visible)
                    row_mismatches += int(effective != wanted) + int(raw_ids != wanted) + int(actual != wanted)
                    # A small top-k must still be selected from the effective scope.
                    top = index.candidates(query, limit=1, source_ids=selected)
                    row_leaks += len({m.payload["source_id"] for m in top} - wanted)
                    checks += 1
                print(f"S4 {name} {flag}/{intent}: leaks={row_leaks} mismatches={row_mismatches}")
                leaks += row_leaks
                mismatches += row_mismatches
    print(f"S4 total: combinations=18 selections={checks} leaks={leaks} mismatches={mismatches}")
    assert leaks == 0
    assert mismatches == 0


def test_unconfirmed_confirmation_and_shares(matrix_db, monkeypatch):
    _, factory, users, space, dept, ids, vectors = matrix_db
    owner = PostgresSourceStore(factory, users["chung"], space_id=space)
    stranger = PostgresSourceStore(factory, users["hai"], space_id=space)
    with pytest.raises(PermissionError):
        stranger.confirm_version(ids["noiquy_v1"], users["hai"])
    with pytest.raises(PermissionError):
        owner.confirm_version(ids["noiquy_v1"], users["hai"])
    first = owner.confirm_version(ids["noiquy_v1"], users["chung"])
    assert owner.confirm_version(ids["noiquy_v1"], users["chung"])["confirmed_at"] == first["confirmed_at"]
    with factory.begin() as db:
        row = db.scalar(select(DocumentVersionRecord).where(DocumentVersionRecord.source_id == ids["noiquy_v2"]))
        row.confirmed_at = row.confirmed_by = None
        row.status = "unverified"
        row.evidence = {"proposed_status": "issued"}
    monkeypatch.setenv("VERSION_FILTER", "on")
    assert {ids["noiquy_v1"], ids["noiquy_v2"]} <= owner.effective_source_ids("hiện hành")
    assert owner.confirm_version(ids["noiquy_v2"], users["chung"])["status"] == "issued"
    assert ids["noiquy_v1"] not in owner.effective_source_ids("hiện hành")
    assert ids["banggia_v2"] not in stranger.scope_source_ids()
    with factory.begin() as db:
        db.add(OrgSourceShareRecord(share_id="share_" + uuid4().hex,
            source_id=ids["banggia_v2"], target_user_id=users["hai"]))
    assert ids["banggia_v2"] in stranger.scope_source_ids()
    assert ids["banggia_v1"] not in stranger.effective_source_ids("hiện hành")
    with factory.begin() as db:
        row = db.get(OrgMemberRecord, (space, users["hai"]))
        row.status = "PENDING"
    assert stranger.effective_source_ids("bản cũ") == set()
    assert CandidateIndex(stranger, vectors, owner_user_id=users["hai"],
                          embedder=DeterministicEmbedder()).candidates("hiện hành") == []


def test_original_intent_fusion_and_lexical_fallback(matrix_db, monkeypatch):
    from types import SimpleNamespace
    from app.research.product_retrieval import _lists_for
    _, factory, users, space, _, ids, vectors = matrix_db
    monkeypatch.setenv("VERSION_FILTER", "on")
    store = PostgresSourceStore(factory, users["hai"], space_id=space)
    expected = store.effective_source_ids("bản cũ")
    index = CandidateIndex(store, vectors, owner_user_id=users["hai"], embedder=DeterministicEmbedder())
    pipeline = ResearchPipeline(store, None, candidate_index=index)
    cfg = SimpleNamespace(retrieval_min_score=-1)
    lists = _lists_for(pipeline, "Quy định", None, cfg, None, 100, "hybrid", version_query="bản cũ")
    assert {c.source_id for c in lists[0]} == expected
    assert all(c.source_id in expected for listing in lists for c in listing)
    assert ids["noiquy_v1"] in {c.source_id for c in lists[0]}
    # Caller-supplied whole-corpus chunks must be filtered before lexical ranking.
    lexical = ResearchPipeline(store, None)
    current = store.effective_source_ids("hiện hành")
    chunks = lexical._retrieve_candidates("hiện hành", store.chunks(), top_k=100,
                                          min_score=-1, source_ids=None)
    assert {c.source_id for c in chunks} <= current
    # An empty derived index takes the fallback over the same effective set.
    empty = CandidateIndex(store, InMemoryVectorStore(vector_size=2), owner_user_id=users["hai"],
                           embedder=DeterministicEmbedder())
    fallback = ResearchPipeline(store, None, candidate_index=empty)
    chunks = fallback._retrieve_candidates("Nội quy công ty", None, top_k=100,
                                           min_score=-1, source_ids=None)
    assert {c.source_id for c in chunks} <= current
