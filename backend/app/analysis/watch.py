"""Theo dõi tài liệu mới (đợt 10): khi có tài liệu mới, tự kiểm hiệu lực và tìm cặp câu có thể mâu thuẫn với tài liệu cũ.

Chỉ dùng luật cố định có sẵn (document_validity, candidate_pairs), không gọi mô hình nên chạy ngay lúc tải lên.
Có phát hiện thì báo người tải lên qua chuông thông báo; "có thể mâu thuẫn" là cặp nghi vấn, cần mở Kiểm tra mâu thuẫn để xác nhận.
"""
from __future__ import annotations

import logging
from datetime import date
from uuid import uuid4

from app.analysis.consistency import candidate_pairs, extract_statements
from app.analysis.domain_tools import document_validity
from app.core.types import SourceChunk


def replacement_pairs(docs: list[tuple[str, str, str]], today: date | None = None) -> set[frozenset[str]]:
    """Cặp tài liệu có quan hệ thay thế (văn bản này nêu "thay thế ... <số hiệu văn bản kia>"). Luật cố định, không gọi mô hình."""
    items = document_validity(docs, today)["documents"]
    return {frozenset((a["source_id"], b["source_id"])) for a in items for b in items
            if a is not b and b.get("number") and b["number"] in (a.get("replaces") or [])}


def watch_findings(new_source_id: str, chunks: list[SourceChunk], today: date | None = None) -> dict:
    """Phát hiện liên quan tới tài liệu mới trong kho (chunks gồm cả tài liệu mới và tài liệu cũ được phép xem)."""
    by: dict[str, list[SourceChunk]] = {}
    for c in chunks:
        by.setdefault(c.source_id, []).append(c)
    if new_source_id not in by or len(by) < 2:
        return {"replaces": [], "replaced_by": None, "conflicts": 0, "examples": []}
    docs = [(sid, cs[0].source_name, "\n".join(c.text for c in sorted(cs, key=lambda c: c.index))) for sid, cs in by.items()]
    items = {d["source_id"]: d for d in document_validity(docs, today)["documents"]}
    new = items[new_source_id]
    replaces = sorted(d["source_name"] for sid, d in items.items()
                      if sid != new_source_id and d.get("number") and d["number"] in (new.get("replaces") or []))
    replaced_by = new["status_note"] if new.get("status") == "REPLACED" else None
    replaced = replacement_pairs(docs, today)
    # văn bản mới thay thế văn bản cũ: khác ngày hiệu lực/con số giữa hai văn bản là thay thế hợp lệ, không phải mâu thuẫn
    pairs = [p for p in candidate_pairs(extract_statements(chunks), max_pairs=50)
             if new_source_id in (p["a"]["source_id"], p["b"]["source_id"])
             and frozenset((p["a"]["source_id"], p["b"]["source_id"])) not in replaced]
    examples = [{"other": (p["b"] if p["a"]["source_id"] == new_source_id else p["a"])["source_name"], "reason": p["reason"]} for p in pairs[:3]]
    return {"replaces": replaces, "replaced_by": replaced_by, "conflicts": len(pairs), "examples": examples}


def notify_findings(session_factory, user_id: str, source_name: str, findings: dict) -> bool:
    """Báo người tải lên qua chuông khi có phát hiện. Lỗi ở đây không làm hỏng việc tải tài liệu."""
    if session_factory is None or not (findings["replaces"] or findings["replaced_by"] or findings["conflicts"]):
        return False
    from app.storage.postgres.models import NotificationRecord

    try:
        with session_factory.begin() as db:
            db.add(NotificationRecord(notification_id="ntf_" + uuid4().hex[:16], user_id=user_id, space_id=None,
                                      kind="doc_watch", payload={"source_name": source_name, **findings}))
        return True
    except Exception:
        logging.getLogger(__name__).exception("doc watch notification failed")
        return False


__all__ = ["notify_findings", "watch_findings"]
