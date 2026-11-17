"""Relation graph acceptance using small legal texts and the scratch database."""
import os
import unicodedata
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.access import filter_version_ids
from app.research.version_relations import normalized_doc_number, relation_edges
from app.storage.postgres.models import (
    DocumentVersionRecord, KnowledgeSourceRecord, OrgMemberRecord, OrgSpaceRecord,
    UserRecord, VersionDiffRecord,
)
from app.storage.postgres.runtime import PostgresSourceStore


TODAY = date(2026, 11, 17)
BASE = "08/2022/TT-BGDĐT"
AMENDMENT = "06/2025/TT-BGDĐT"
REPLACEMENT = "06/2026/TT-BGDĐT"


def version(number, year, *, kind=None, target=BASE, **overrides):
    return {"source_id": number, "doc_number": number, "family_key": number,
            "owner_user_id": "owner", "status": "issued", "confirmed_at": "confirmed",
            "effective_from": date(year, 1, 1),
            "relations": [{"type": kind, "target_doc_number": target}] if kind else [],
            **overrides}


@pytest.fixture
def chain(monkeypatch):
    monkeypatch.setenv("VERSION_RELATIONS", "1")
    return [version(BASE, 2022), version(AMENDMENT, 2025, kind="amends"),
            version(REPLACEMENT, 2026, kind="replaces")]


def current(versions, visible=None, query="hiện hành"):
    return filter_version_ids({v["source_id"] for v in versions} if visible is None else visible,
                              versions, query, today=TODAY)


def test_three_document_chain_and_old_intent(chain):
    assert current(chain) == {REPLACEMENT}
    edges = relation_edges(chain)
    assert {(e.new_source_id, e.old_source_id, e.kind, e.family_key) for e in edges} == {
        (AMENDMENT, BASE, "amends", BASE), (REPLACEMENT, BASE, "replaces", BASE)}
    for query in ("bản cũ", "so sánh", "trước đây"):
        assert current(chain, query=query) == {BASE, AMENDMENT, REPLACEMENT}


def test_amends_keeps_both_and_unseen_replacement_cannot_retire(chain):
    assert current(chain[:2]) == {BASE, AMENDMENT}
    assert current(chain, {BASE, AMENDMENT}) == {BASE, AMENDMENT}
    assert current(chain, {BASE}) == {BASE}
    assert current(chain, set()) == set()


@pytest.mark.parametrize("overrides", [
    {"confirmed_at": None}, {"status": "draft"}, {"status": "unverified"},
    {"status": "superseded"}, {"effective_from": date(2027, 1, 1)}, {"effective_from": None},
    {"owner_user_id": "other"}, {"space_id": "other"},
])
def test_only_visible_confirmed_issued_effective_replacer_retires(chain, overrides):
    chain[2].update(overrides)
    assert {BASE, AMENDMENT} <= current(chain)


def test_unconfirmed_target_and_non_replacement_relation_are_preserved(chain):
    chain[0]["confirmed_at"] = None
    assert current(chain) == {BASE, AMENDMENT, REPLACEMENT}
    chain[0]["confirmed_at"] = "confirmed"
    chain[2]["relations"][0]["type"] = "partially_repeals"
    assert current(chain) == {BASE, AMENDMENT, REPLACEMENT}


def test_normalized_numbers_and_transitive_amendments(chain):
    raw = unicodedata.normalize("NFD", " 8 / 2022 / tt – bgdđt. ")
    assert normalized_doc_number(raw) == BASE
    chain[2]["relations"][0]["target_doc_number"] = raw
    chain.append(version("01/2026/TT-BGDĐT", 2026, kind="amends", target=AMENDMENT))
    assert current(chain) == {REPLACEMENT}
    assert {e.family_key for e in relation_edges(chain)} == {BASE}


def test_new_flag_default_off_and_legacy_synthetic_path(chain, monkeypatch):
    monkeypatch.delenv("VERSION_RELATIONS")
    assert current(chain) == {BASE, AMENDMENT, REPLACEMENT}
    monkeypatch.setenv("VERSION_RELATIONS", "0")
    assert current(chain) == {BASE, AMENDMENT, REPLACEMENT}
    monkeypatch.setenv("VERSION_RELATIONS", "1")
    policies = [version("CS-API-03", 2025, source_id="old"),
                version("CS-API-03", 2026, source_id="new")]
    assert current(policies) == {"new"}


def legal_text(number, year, minutes, kind=None):
    title = f"Sửa đổi, bổ sung Thông tư số {BASE}\n" if kind == "amends" else ""
    replaces = f"Thông tư này thay thế Thông tư số {BASE}.\n" if kind == "replaces" else ""
    return (f"Số: {number}\n{title}Ngày ban hành: 01/01/{year}\n"
            f"Hiệu lực từ: 01/02/{year}\nTình trạng: Đã ban hành\n"
            f"Điều 1. Yêu cầu đào tạo\n1. Phải chờ {minutes} phút.\n"
            f"Điều 2. Hiệu lực thi hành\n{replaces}Thông tư này có hiệu lực từ ngày 01/02/{year}.")


@pytest.fixture
def relation_db(monkeypatch):
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    for key, value in {"VERSION_RELATIONS": "1", "VERSION_DIFF": "1", "VERSION_PROPOSE": "1",
                       "VERSION_FILTER": "on", "CHUNK_MODE": "legal"}.items():
        monkeypatch.setenv(key, value)
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = sessionmaker(engine)
    owners = ["r1_" + uuid4().hex for _ in range(2)]
    space = "r1_" + uuid4().hex
    with factory.begin() as db:
        for owner in owners:
            db.add(UserRecord(user_id=owner, username=owner, display_name="R1", password_hash="test-only"))
        db.add(OrgSpaceRecord(space_id=space, name="R1"))
    try:
        yield factory, [PostgresSourceStore(factory, owner) for owner in owners], space
    finally:
        with factory.begin() as db:
            db.execute(delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.owner_user_id.in_(owners)))
            db.execute(delete(OrgMemberRecord).where(OrgMemberRecord.space_id == space))
            db.execute(delete(OrgSpaceRecord).where(OrgSpaceRecord.space_id == space))
            db.execute(delete(UserRecord).where(UserRecord.user_id.in_(owners)))
        engine.dispose()


def import_chain(store, prefix=""):
    return [store.import_text(prefix + number + ".txt", legal_text(number, year, minutes, kind))["source_id"]
            for number, year, minutes, kind in [(BASE, 2022, 10, None),
                (AMENDMENT, 2025, 20, "amends"), (REPLACEMENT, 2026, 30, "replaces")]]


def diff_rows(factory, source_ids):
    with factory() as db:
        return db.scalars(select(VersionDiffRecord).where(
            VersionDiffRecord.new_source_id.in_(source_ids))).all()


def test_real_text_diff_confirm_reverse_order_and_filter(relation_db, monkeypatch):
    factory, (store, _), _ = relation_db
    ids = import_chain(store)
    assert store.get_version(ids[1])["relations"][0]["type"] == "amends"
    assert store.get_version(ids[2])["relations"][0]["type"] == "replaces"
    assert diff_rows(factory, ids) == []
    for sid in reversed(ids[1:]):
        store.confirm_version(sid, store.owner_user_id)
    assert diff_rows(factory, ids) == []
    store.confirm_version(ids[0], store.owner_user_id)
    rows = diff_rows(factory, ids)
    assert len(rows) > 0
    assert {(r.new_source_id, r.old_source_id) for r in rows} == {(ids[1], ids[0]), (ids[2], ids[0])}
    assert {r.family_key for r in rows} == {BASE}
    assert store.effective_source_ids("hiện hành") == {ids[2]}
    # A selection is intersected after computing the visible current versions.
    assert store.effective_source_ids("hiện hành", [ids[0]]) == set()
    assert store.effective_source_ids("bản cũ") == set(ids)
    evidence = store.version_diff_evidence("So sánh")
    assert {c.source_id for c in evidence} == {ids[1], ids[2]}
    assert store.version_diff_evidence("So sánh", [ids[2]]) is None
    before = len(rows)
    store.confirm_version(ids[0], store.owner_user_id)
    assert store.refresh_version_diffs() == before
    assert len(diff_rows(factory, ids)) == before
    monkeypatch.setenv("VERSION_RELATIONS", "0")
    assert store.effective_source_ids("hiện hành") == set(ids)
    assert store.version_diff_evidence("So sánh") is None
    assert len(diff_rows(factory, ids)) == before


def test_public_refresh_after_sql_confirmation_scope_stale_and_off(relation_db, monkeypatch):
    factory, (store, stranger), space = relation_db
    # A different owner's graph remains untouched by the public refresh.
    other_ids = import_chain(stranger)
    for sid in other_ids:
        stranger.confirm_version(sid, stranger.owner_user_id)
    other_before = {r.id for r in diff_rows(factory, other_ids)}
    monkeypatch.setenv("VERSION_DIFF", "0")
    ids = import_chain(store)
    space_ids = import_chain(store, prefix="space-")
    with factory.begin() as db:
        for sid in space_ids:
            db.get(KnowledgeSourceRecord, sid).space_id = space
        for row in db.scalars(select(DocumentVersionRecord).where(
                DocumentVersionRecord.source_id.in_(ids + space_ids))):
            row.confirmed_at, row.confirmed_by, row.status = datetime.now(timezone.utc), store.owner_user_id, "issued"
    assert store.refresh_version_diffs() == 0
    assert diff_rows(factory, ids) == []
    monkeypatch.setenv("VERSION_DIFF", "1")
    scoped = PostgresSourceStore(factory, store.owner_user_id, space_id=space)
    assert scoped.refresh_version_diffs() > 0
    space_before = {r.id for r in diff_rows(factory, space_ids)}
    assert store.refresh_version_diffs() > 0
    rows = diff_rows(factory, ids)
    assert not set(space_ids) & {r.new_source_id for r in rows}
    assert {r.id for r in diff_rows(factory, space_ids)} == space_before
    assert {r.id for r in diff_rows(factory, other_ids)} == other_before
    # Removing a confirmed relation must remove its stale derived edge.
    with factory.begin() as db:
        row = db.scalar(select(DocumentVersionRecord).where(DocumentVersionRecord.source_id == ids[2]))
        row.relations = []
    store.confirm_version(ids[2], store.owner_user_id)
    assert {r.new_source_id for r in diff_rows(factory, ids)} == {ids[1]}
    monkeypatch.setenv("VERSION_FILTER", "off")
    assert store.effective_source_ids("hiện hành") == set(ids)


def test_hidden_replacement_does_not_filter_visible_base_or_amendment(relation_db):
    factory, (owner, reader), space = relation_db
    ids = import_chain(owner)
    for sid in ids:
        owner.confirm_version(sid, owner.owner_user_id)
    with factory.begin() as db:
        for store in (owner, reader):
            db.add(OrgMemberRecord(space_id=space, user_id=store.owner_user_id,
                                   level="EXECUTIVE", status="ACTIVE"))
        for sid in ids:
            source = db.get(KnowledgeSourceRecord, sid)
            source.space_id = space
            source.classification = "PRIVATE" if sid == ids[2] else "COMPANY"
    scoped = PostgresSourceStore(factory, reader.owner_user_id, space_id=space)
    assert scoped.effective_source_ids("hiện hành") == set(ids[:2])
    assert scoped.effective_source_ids("hiện hành", [ids[0]]) == {ids[0]}
    evidence = scoped.version_diff_evidence("So sánh")
    assert evidence and {c.source_id for c in evidence} == {ids[1]}
    with factory.begin() as db:
        db.get(KnowledgeSourceRecord, ids[2]).classification = "COMPANY"
    assert scoped.effective_source_ids("hiện hành") == {ids[2]}


def test_diff_flag_off_and_relation_flag_off(relation_db, monkeypatch):
    factory, (store, _), _ = relation_db
    monkeypatch.delenv("VERSION_RELATIONS")
    ids = import_chain(store)
    for sid in ids:
        store.confirm_version(sid, store.owner_user_id)
    assert diff_rows(factory, ids) == []
    assert store.refresh_version_diffs() == 0
    assert store.effective_source_ids("hiện hành") == set(ids)
    monkeypatch.setenv("VERSION_RELATIONS", "1")
    monkeypatch.setenv("VERSION_DIFF", "0")
    monkeypatch.setattr(store, "_refresh_version_diffs", lambda *args: pytest.fail("diff writes while off"))
    store.confirm_version(ids[0], store.owner_user_id)
    assert store.refresh_version_diffs() == 0
    assert store.version_diff_evidence("So sánh") is None
