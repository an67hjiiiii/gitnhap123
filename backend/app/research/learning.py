"""Học từ người dùng (Đợt 8, P1-5): lưu và đọc ví dụ chọn tác tử theo người và không gian. Chỉ ô chat sản phẩm dùng."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.research.agent_selection import DESCRIPTIONS
from app.storage.postgres.models import RoutingExampleRecord

MAX_EXAMPLES = 200  # ví dụ gần nhất mỗi người trong một không gian


def record_example(session_factory, user_id: str, space_id: str | None, query: str, agent: str, source: str = "clarify") -> bool:
    query = " ".join(str(query or "").split())[:1000]
    if session_factory is None or agent not in DESCRIPTIONS or not query:
        return False
    with session_factory.begin() as db:
        db.add(RoutingExampleRecord(example_id=f"rx_{uuid4().hex[:16]}", owner_user_id=str(user_id), space_id=space_id,
                                    query=query, agent=agent, source=source[:16]))
    return True


def load_examples(session_factory, user_id: str, space_id: str | None) -> list[tuple[str, str]]:
    """[(câu hỏi, tác tử)], lựa chọn mới nhất cho mỗi câu (người dùng đổi ý thì lấy lần sau)."""
    if session_factory is None:
        return []
    with session_factory() as db:
        rows = db.execute(select(RoutingExampleRecord.query, RoutingExampleRecord.agent).where(
            RoutingExampleRecord.owner_user_id == str(user_id),
            RoutingExampleRecord.space_id.is_(None) if space_id is None else RoutingExampleRecord.space_id == space_id,
        ).order_by(RoutingExampleRecord.created_at.desc()).limit(MAX_EXAMPLES)).all()
    seen: dict[str, str] = {}
    for q, a in rows:
        seen.setdefault(q, a)
    return list(seen.items())
