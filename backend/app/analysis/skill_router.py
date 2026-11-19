"""Bộ định tuyến kỹ năng cho ô chat "Tự động" (đợt 4, bản làm thử 19/11).

Luật cố định, không gọi mô hình: câu hỏi khớp đúng MỘT kỹ năng (và có loại tài liệu phù hợp khi kỹ năng cần)
thì gọi kỹ năng đó; khớp nhiều kỹ năng hoặc không khớp thì trả None để pipeline sản phẩm tự chọn
trả lời thẳng hay chia việc cho nhiều tác tử (đã có sẵn). Chỉ dùng cho ô chat sản phẩm; thực nghiệm A/B/C không đi qua đây.
"""
from __future__ import annotations

import re

from app.ingestion.doc_type import _fold

# kỹ năng: (tên hiển thị, mẫu ý định trên chữ đã bỏ dấu, loại tài liệu cần có hoặc None)
SKILLS: dict[str, tuple[str, str, frozenset[str] | None]] = {
    "contract_review": (
        "Rà soát hợp đồng",
        r"\b(ra soat|kiem tra|xem xet|danh gia)\b.{0,30}\bhop dong\b|\bdieu khoan\b.{0,25}\b(bat loi|rui ro|phat|nguy hiem)\b",
        frozenset({"contract"}),
    ),
    "validity": (
        "Hiệu lực văn bản",
        r"\b(con hieu luc|het hieu luc|hieu luc tu|bi thay the|hieu luc)\b",
        frozenset({"legal_doc", "regulation"}),
    ),
    "approver": (
        "Ai duyệt",
        r"\b(ai duyet|cap duyet|ai phe duyet|ai ky duyet|ai la nguoi duyet|can ai duyet|nguoi duyet)\b",
        None,
    ),
    "procedure": (
        "Quy trình từng bước",
        r"\b(thu tuc|quy trinh|cac buoc|trinh tu|can (nhung )?giay to gi|ho so gom)\b",
        None,
    ),
    "conditions": (
        "Kiểm tra điều kiện",
        r"\bco (duoc|du dieu kien)\b.{0,80}\bkhong\b|\b(du dieu kien|du tieu chuan)\b",
        None,
    ),
}


def route_skill(query: str, doc_types: list[str | None]) -> dict | None:
    """Trả {"skill", "label", "reason"} hoặc None (để pipeline xử lý)."""
    text = _fold(query)
    types = {t for t in doc_types if t}
    hits = [key for key, (_, pattern, _) in SKILLS.items() if re.search(pattern, text)]
    usable = [k for k in hits if SKILLS[k][2] is None or SKILLS[k][2] & types]
    if len(usable) != 1:
        return None  # không khớp, hoặc yêu cầu nhiều mảng: để bộ điều phối nhiều tác tử
    key = usable[0]
    label, _, needs = SKILLS[key]
    reason = f'Câu hỏi khớp kỹ năng "{label}"'
    if needs:
        reason += " và có tài liệu phù hợp trong phạm vi hỏi"
    return {"skill": key, "label": label, "reason": reason, "doc_types": sorted(needs) if needs else None}


__all__ = ["SKILLS", "route_skill"]
