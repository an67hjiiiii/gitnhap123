"""Tự phân loại tài liệu khi tải lên (đợt 3, 19/11): luật nhận dạng cố định, không gọi mô hình.

Nhãn lưu ở knowledge_sources.display_metadata["doc_type"]; người dùng sửa được ("doc_type_by": "user").
Không chắc thì trả "other" thay vì đoán. Nhãn dùng để gợi ý kỹ năng và nạp kiến thức ngành ở các đợt sau.
"""
from __future__ import annotations

import re
import unicodedata

DOC_TYPES: dict[str, str] = {
    "contract": "Hợp đồng",
    "regulation": "Quy chế",
    "internal_rules": "Nội quy",
    "transcript": "Bảng điểm",
    "legal_doc": "Văn bản pháp quy",
    "software_spec": "Đặc tả phần mềm",
    "lecture": "Bài giảng",
    "other": "Khác",
}

MIN_SCORE = 4  # dưới ngưỡng này coi là chưa đủ dấu hiệu → "other"

# (nhãn, mẫu, điểm). Tiêu đề (vài dòng đầu) nặng điểm; dấu hiệu trong thân nhẹ hơn và tính tối đa 3 lần mỗi mẫu.
_TITLE = [
    ("contract", r"\bhop dong\b", 6),
    ("regulation", r"\bquy che\b", 6),
    ("internal_rules", r"\bnoi quy\b", 6),
    ("transcript", r"\bbang diem\b|\bket qua hoc tap\b", 6),
    ("legal_doc", r"\b(nghi dinh|thong tu|luat|quyet dinh|nghi quyet|chi thi)\b", 5),
    ("software_spec", r"\b(dac ta|software requirements?|srs)\b", 6),
    ("lecture", r"\b(bai giang|giao trinh|lecture)\b", 6),
]
_BODY = [
    ("contract", r"\bben a\b", 2),
    ("contract", r"\bben b\b", 2),
    ("contract", r"\bhai ben\b|\bcac ben\b", 1),
    ("contract", r"\bgia tri hop dong\b|\bthanh toan\b|\bboi thuong\b|\bphat vi pham\b", 1),
    ("legal_doc", r"\bcan cu\b", 2),
    ("legal_doc", r"\bcong hoa xa hoi chu nghia viet nam\b", 2),
    ("legal_doc", r"\bso:?\s*\d+/\d{4}/", 2),
    ("legal_doc", r"\bco hieu luc (thi hanh )?(ke )?tu ngay\b|\bthay the\b", 1),
    ("regulation", r"\bchuong [ivxlc\d]+\b", 1),
    ("regulation", r"\bdieu \d+\b", 1),
    ("regulation", r"\bsinh vien\b|\bhoc phan\b|\bdao tao\b|\bchi tieu\b", 1),
    ("internal_rules", r"\bnguoi lao dong\b", 2),
    ("internal_rules", r"\bnghi phep\b|\bky luat lao dong\b|\blam them gio\b|\bthu viec\b", 1),
    ("transcript", r"\b(mssv|ma sv|ma sinh vien)\b", 3),
    ("transcript", r"\b(dtb|diem trung binh|gpa)\b", 2),
    ("transcript", r"\bren luyen\b|\bxep loai\b", 1),
    ("software_spec", r"\b(n?fr|req|uc)-?\d{1,3}\b", 2),
    ("software_spec", r"\byeu cau (chuc nang|phi chuc nang)\b|\bshall\b|\buse case\b|\bapi\b", 1),
    ("lecture", r"\bmuc tieu (bai hoc|chuong)\b|\bcau hoi on tap\b|\bvi du\b|\bdinh nghia\b", 1),
]


def _fold(text: str) -> str:
    """Bỏ dấu, chữ thường: so khớp không phụ thuộc cách gõ dấu tiếng Việt."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()


def _title(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # tên văn bản thường nằm sau quốc hiệu, tên cơ quan, số hiệu: xét 8 dòng đầu
    return " ".join(lines[:8])


def classify_document(source_name: str, text: str) -> str:
    """Trả về một khóa trong DOC_TYPES."""
    head = _fold(source_name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ") + " " + _title(text))
    body = _fold(text[:8000])
    scores = dict.fromkeys(DOC_TYPES, 0)
    for label, pattern, weight in _TITLE:
        if re.search(pattern, head):
            scores[label] += weight
    for label, pattern, weight in _BODY:
        scores[label] += weight * min(3, len(re.findall(pattern, body)))
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= MIN_SCORE else "other"


__all__ = ["DOC_TYPES", "classify_document"]
