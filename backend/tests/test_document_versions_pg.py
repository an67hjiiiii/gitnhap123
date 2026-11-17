import os
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.ingestion.version_meta import propose_version
from app.storage.postgres.models import DocumentVersionRecord, UserRecord
from app.storage.postgres.runtime import PostgresSourceStore

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set")


@pytest.fixture
def stores(monkeypatch):
    monkeypatch.delenv("VERSION_PROPOSE", raising=False)
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = sessionmaker(engine)
    owners = ["p3b_" + uuid4().hex for _ in range(2)]
    with factory.begin() as db:
        for owner in owners:
            db.add(UserRecord(user_id=owner, username=owner, display_name="P3B test", password_hash="test-only"))
    try:
        yield factory, [PostgresSourceStore(factory, owner) for owner in owners]
    finally:
        with factory.begin() as db:
            db.execute(delete(UserRecord).where(UserRecord.user_id.in_(owners)))
        engine.dispose()


TEXT = "Số hiệu: CS-DN-01\nPhiên bản: 2.0\nNgày ban hành: 01/09/2026\nHiệu lực từ: 01/10/2026\nTình trạng: Đã ban hành\nĐiều 1. Phạm vi áp dụng\nMọi tài khoản."


def test_off_does_not_call_proposer_or_create_row(stores, monkeypatch):
    _, (store, _) = stores
    def forbidden(*args):
        pytest.fail("proposer called with feature disabled")
    monkeypatch.setattr("app.ingestion.version_meta.propose_version", forbidden)
    imported = store.import_text("policy.txt", TEXT)
    assert store.get_version(imported["source_id"]) is None
    assert store.source_status(imported["source_id"])["status"] == "READY"
    monkeypatch.setenv("VERSION_PROPOSE", "0")
    assert store.import_text("policy.txt", TEXT) == {**imported, "chunks_added": 0}


def test_enabled_import_upsert_ownership_confirmation(stores, monkeypatch):
    factory, (store, stranger) = stores
    monkeypatch.setenv("VERSION_PROPOSE", "1")
    imported = store.import_text("policy.txt", TEXT)
    source_id = imported["source_id"]
    first = store.get_version(source_id)
    assert first["status"] == "unverified"
    assert first["evidence"]["proposed_status"] == "issued"
    assert first["confirmed_by"] is None and first["confirmed_at"] is None
    assert first["issued_on"] == date(2026, 9, 1)
    assert first["effective_from"] == date(2026, 10, 1)
    assert store.source_status(source_id)["status"] == "READY"
    assert stranger.get_version(source_id) is None
    with pytest.raises(PermissionError):
        stranger.upsert_version_proposal(source_id, propose_version(TEXT, "policy.txt"))
    with pytest.raises(PermissionError):
        store.upsert_version_proposal("missing", {})
    store.import_text("policy.txt", TEXT)
    second = store.get_version(source_id)
    assert second["id"] == first["id"]
    with factory.begin() as db:
        row = db.scalar(select(DocumentVersionRecord).where(DocumentVersionRecord.source_id == source_id))
        row.status = "issued"
        row.confirmed_by = store.owner_user_id
        row.confirmed_at = datetime.now(timezone.utc)
    proposal = propose_version(TEXT.replace("2.0", "3.0"), "policy.txt")
    store.upsert_version_proposal(source_id, proposal)
    confirmed = store.get_version(source_id)
    assert confirmed["status"] == "issued" and confirmed["version_label"] == "2.0"
    assert confirmed["confirmed_at"] is not None
