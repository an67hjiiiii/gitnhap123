"""Đổi tên, ghim, xóa (ẩn) cuộc trò chuyện: kho PostgresConversationStore chạy trên SQLite trong bộ nhớ."""
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.storage.postgres.base import Base
from app.storage.postgres.models import ConversationMessageRecord
from app.storage.postgres.runtime import PostgresAuthStore, PostgresConversationStore


@pytest.fixture()
def stores():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.create_function("btrim", 1, lambda v: None if v is None else v.strip()))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    auth = PostgresAuthStore(factory)
    a = auth.register(email="a@x.vn", password="matkhau-a-123")["user_id"]
    b = auth.register(email="b@x.vn", password="matkhau-b-123")["user_id"]
    return factory, PostgresConversationStore(factory, a), PostgresConversationStore(factory, b)


def test_rename_keeps_order_and_activity_time(stores):
    _, mine, _ = stores
    first = mine.create("Cũ")
    second = mine.create("Mới")
    before = mine.get(first["conversation_id"])["updated_at"]
    renamed = mine.update(first["conversation_id"], title="  Kế hoạch sáp nhập  ")
    assert renamed["title"] == "Kế hoạch sáp nhập" and renamed["updated_at"] == before
    assert [c["conversation_id"] for c in mine.list()][0] == second["conversation_id"]  # đổi tên không đẩy lên đầu
    with pytest.raises(ValueError):
        mine.update(first["conversation_id"], title="   ")
    with pytest.raises(ValueError):
        mine.update(first["conversation_id"], title="x" * 121)


def test_pin_moves_to_top_and_unpin(stores):
    _, mine, _ = stores
    old = mine.create("Cũ nhất")
    mine.create("Mới hơn")
    assert mine.update(old["conversation_id"], pinned=True)["pinned"] is True
    top = mine.list()[0]
    assert top["conversation_id"] == old["conversation_id"] and top["pinned"] is True
    mine.update(old["conversation_id"], pinned=False)
    assert mine.list()[0]["conversation_id"] != old["conversation_id"]


def test_hide_keeps_messages_and_can_undo(stores):
    factory, mine, _ = stores
    conv = mine.create("Sẽ xóa")
    mine.add_message(conv["conversation_id"], "USER", "câu hỏi", run_id=None)
    assert mine.update(conv["conversation_id"], hidden=True)["hidden"] is True
    assert mine.list() == [] and mine.get(conv["conversation_id"]) is None
    with factory() as db:  # dữ liệu nghiên cứu vẫn còn
        assert db.scalars(select(ConversationMessageRecord).where(
            ConversationMessageRecord.conversation_id == conv["conversation_id"])).all()
    mine.update(conv["conversation_id"], hidden=False)
    assert mine.get(conv["conversation_id"])["messages"][0]["content"] == "câu hỏi"


def test_cannot_touch_someone_elses_conversation(stores):
    _, mine, theirs = stores
    conv = theirs.create("Của người khác")
    with pytest.raises(LookupError):
        mine.update(conv["conversation_id"], title="chiếm", hidden=True)
    assert theirs.get(conv["conversation_id"])["title"] == "Của người khác"
