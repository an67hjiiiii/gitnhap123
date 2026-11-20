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
    # Đợt 4: so sánh hai phiên bản (bản cũ/bản mới) theo Điều/Khoản; trang So sánh xem chi tiết
    "compare": (
        "So sánh phiên bản",
        r"\b(so sanh|doi chieu)\b.{0,60}\b(ban|phien ban|quy che|quy dinh|van ban|cu|moi|nam)\b|\b(ban moi|phien ban moi)\b.{0,40}\b(khac|thay doi|diem moi)\b|\bthay doi gi\b.{0,40}\b(so voi|ban cu)\b",
        None,
    ),
    # Đợt 5 (P1-3): câu hỏi trắc nghiệm có phương án, đáp án, nguồn (dùng công cụ tạo câu hỏi sẵn có)
    "quiz": (
        "Tạo câu hỏi trắc nghiệm",
        r"\b(trac nghiem|cau hoi on tap|de on tap|bo cau hoi|cau hoi kiem tra|ngan hang cau hoi)\b",
        None,
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


# yêu cầu soạn nội dung mới (câu hỏi ôn tập, tóm tắt, văn bản) không phải tra quy định: nhắc tới "quy trình" hay
# "hợp đồng" trong đó chỉ là chủ đề, nên để pipeline trả lời thay vì ép vào kỹ năng tra cứu
COMPOSE = r"\b(tao|soan|viet|lap)\b.{0,30}\b(cau hoi|de thi|bai kiem tra|trac nghiem|van ban|email|thu|bao cao|tom tat)\b|\b(trac nghiem|on tap|tom tat|tom luoc)\b"


def route_skill(query: str, doc_types: list[str | None]) -> dict | None:
    """Trả {"skill", "label", "reason"} hoặc None (để pipeline xử lý)."""
    text = _fold(query)
    if re.search(SKILLS["quiz"][1], text):  # tạo câu hỏi trắc nghiệm là kỹ năng riêng, đi trước luật "soạn nội dung"
        return {"skill": "quiz", "label": SKILLS["quiz"][0], "reason": 'Yêu cầu tạo câu hỏi trắc nghiệm', "doc_types": None}
    if re.search(COMPOSE, text):
        return None
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
