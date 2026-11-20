"""Đợt 8 (P1-5): học từ người dùng chỉ ở ô chat sản phẩm; bộ chọn không có ví dụ cho kết quả như cũ."""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.research.agent_selection import LEARNED_VERSION, SELECTION_VERSION, clarify_options, select_agents
from app.research.learning import load_examples, record_example
from app.storage.postgres.base import Base
from app.storage.postgres.models import UserRecord

# mô hình nhúng giả: mọi mô tả tác tử như nhau (hòa điểm → mơ hồ); câu "mua máy chiếu" và câu tương tự gần nhau
VEC = {"mua": (1.0, 0.0, 0.0), "khac": (0.0, 1.0, 0.0)}


def embed(text: str):
    t = text.casefold()
    if "máy chiếu" in t or "máy in" in t:
        return VEC["mua"]
    if "trình bày" in t:
        return (0.9, 0.1, 0.0)
    return (0.5, 0.5, 0.5)


Q = "Việc mua máy chiếu này cần xem những gì trước khi trình?"


def test_without_examples_selection_is_unchanged():
    a, b = select_agents(Q, embed), select_agents(Q, embed, [])
    assert a == b and a["version"] == SELECTION_VERSION and a["learned_from"] == {} and a["ambiguous"]


def test_similar_example_breaks_tie_and_stops_asking_back():
    sel = select_agents("Mua máy in cho phòng cần xem những gì trước khi trình?", embed, [(Q, "procedure")])
    assert sel["primary"] == "procedure" and not sel["ambiguous"] and sel["version"] == LEARNED_VERSION
    assert clarify_options("Mua máy in cho phòng cần xem những gì trước khi trình?", sel) is None
    far = select_agents("Câu hỏi khác hẳn về lương thưởng cuối năm nay?", embed, [(Q, "procedure")])
    assert far["learned_from"] == {}  # không giống ví dụ nào: không cộng điểm


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.create_function("btrim", 1, lambda v: None if v is None else v.strip()))
    Base.metadata.create_all(engine)
    f = sessionmaker(engine, expire_on_commit=False)
    with f.begin() as s:
        s.add_all([UserRecord(user_id=u, email=f"{u}@x.vn", display_name=u, password_hash="x") for u in ("an", "binh")])
    return f


def test_examples_are_per_user_and_space_and_latest_wins(factory):
    assert record_example(factory, "an", None, Q, "terms")
    assert record_example(factory, "an", None, Q, "procedure", "reselect")   # đổi ý: lấy lần sau
    assert record_example(factory, "an", "sp_1", "Câu trong tổ chức", "figures")
    assert not record_example(factory, "an", None, Q, "bogus")               # tác tử không có: bỏ
    assert load_examples(factory, "an", None) == [(Q, "procedure")]
    assert load_examples(factory, "an", "sp_1") == [("Câu trong tổ chức", "figures")]
    assert load_examples(factory, "binh", None) == []
    assert load_examples(None, "an", None) == []


def test_pipeline_ignores_examples_outside_work_pack():
    """Bộ Phần mềm và thực nghiệm A/B/C: ví dụ bị bỏ trước khi chạy, không tới bộ chọn."""
    import inspect

    from app.research.pipeline import ResearchPipeline
    src = inspect.getsource(ResearchPipeline.run)
    assert src.index('kwargs.pop("routing_examples"') < src.index("if active_pack_name() != WORK_PACK")
