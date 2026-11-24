"""Công cụ của tác tử (23/11, chủ dự án duyệt; chỉ ô chat sản phẩm, thực nghiệm A/B/C không dùng).

Tác tử trả lời chưa đủ (PARTIAL/NO_EVIDENCE) thì tự gọi công cụ tìm kiếm với điều còn thiếu, nhận thêm tối đa
TOOL_SEARCH_CHUNKS đoạn mới rồi làm lại một lần; kết quả mới chỉ được nhận khi tốt hơn. Máy tính ([[= ... ]]) đã có sẵn.
Mặc định TẮT (đo 23/11: dùng 4 lần trên 82 câu khóa, 3 câu thành sai, 0 câu đúng lên với qwen3:4b); bật bằng PRODUCT_AGENT_TOOLS=on.
"""
from __future__ import annotations

import os

TOOL_SEARCH_CHUNKS = 3
_RANK = {"COMPLETE": 2, "PARTIAL": 1}
# ghi chú nội bộ của hệ thống trong missing_information, không phải điều người dùng hỏi
_INTERNAL = ("citation", "empty answer", "relevant evidence", "numbers not found", "general knowledge")


def agent_tools_enabled() -> bool:
    return os.getenv("PRODUCT_AGENT_TOOLS", "off").strip().lower() in {"1", "on", "true", "yes"}


def status_rank(status: str | None) -> int:
    return _RANK.get(str(status or "").upper(), 0)


def tool_query(question: str, missing: list[str] | None) -> str:
    """Câu tìm kiếm của tác tử: mục tiêu việc + điều còn thiếu (bỏ ghi chú nội bộ)."""
    need = [m for m in (missing or []) if m and not any(k in m.lower() for k in _INTERNAL)]
    return " ".join([question, *need[:3]]).strip()
