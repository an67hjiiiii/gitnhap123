"""Ghi nhật ký truy cập tài liệu mức Mật (đợt 9). Chỉ ghi thao tác (xem / AI đọc khi trả lời), không ghi nội dung câu hỏi.

Lỗi ghi nhật ký không được làm hỏng việc chính của người dùng: ghi log lỗi rồi bỏ qua.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from sqlalchemy import select

from app.storage.postgres.models import KnowledgeSourceRecord, OrgSecretAccessRecord

AUDITED_CLASSIFICATIONS = ("SECRET",)


def source_ids_of_chunks(chunk_ids: Iterable[str]) -> set[str]:
    return {str(c).rsplit("_c", 1)[0] for c in chunk_ids if "_c" in str(c)}


def run_read_source_ids(run: dict[str, Any]) -> set[str]:
    """Tài liệu có đoạn được đưa cho mô hình hoặc được trích trong một lượt chạy."""
    chunks: list[str] = []
    for r in run.get("task_results") or []:
        chunks += list(r.get("evidence_ids") or []) + list(r.get("citations") or [])
    return source_ids_of_chunks(chunks)


def log_secret_access(session_factory, user_id: str, source_ids: Iterable[str], action: str) -> int:
    ids = sorted(set(source_ids))
    if session_factory is None or not ids:
        return 0
    try:
        with session_factory.begin() as db:
            rows = db.execute(select(KnowledgeSourceRecord.source_id, KnowledgeSourceRecord.space_id).where(
                KnowledgeSourceRecord.source_id.in_(ids),
                KnowledgeSourceRecord.classification.in_(AUDITED_CLASSIFICATIONS),
                KnowledgeSourceRecord.space_id.is_not(None),
            )).all()
            db.add_all([OrgSecretAccessRecord(space_id=space, source_id=sid, user_id=user_id, action=action) for sid, space in rows])
            return len(rows)
    except Exception:  # nhật ký là phụ: không chặn người dùng xem hay hỏi
        logging.getLogger(__name__).exception("secret access log failed")
        return 0


__all__ = ["AUDITED_CLASSIFICATIONS", "log_secret_access", "run_read_source_ids", "source_ids_of_chunks"]
