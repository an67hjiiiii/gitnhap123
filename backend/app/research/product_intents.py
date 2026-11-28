from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


_INTENT_RESPONSES = {
    "greeting": {
        "hi",
        "hello",
        "xin chao",
        "chao",
        "chao ban",
        "chao tro ly",
        "alo",
    },
    "thanks": {"thanks", "thank you", "cam on", "cam on ban"},
    "identity": {
        "ban la ai",
        "xin chao ban la ai",
        "chao ban ban la ai",
        "ban la gi",
        "gioi thieu ve ban",
        "xin chao ban la ai va giup duoc gi",
        "chao ban ban la ai va giup duoc gi",
        "ban la ai va giup duoc gi",
        "ban la ai va lam duoc gi",
    },
    "capabilities": {
        "ban lam duoc gi",
        "toi co the hoi gi",
        "ban giup duoc gi",
        "ban co the giup gi",
        "he thong nay lam duoc gi",
    },
}

_RESPONSES = {
    "greeting": (
        "Chào bạn! Tôi là trợ lý tài liệu OrchestrIQ Studio. Bạn có thể tải tài liệu vào "
        "kho tri thức và đặt câu hỏi hoặc yêu cầu phân tích, đối chiếu, tra cứu quy định có trích dẫn nguồn."
    ),
    "thanks": "Rất vui được hỗ trợ. Bạn có thể tiếp tục đặt câu hỏi về các tài liệu đã tải lên.",
    "identity": (
        "Tôi là trợ lý tài liệu OrchestrIQ Studio. Tôi trả lời câu hỏi dựa trên tài liệu bạn cung cấp "
        "kèm trích dẫn nguồn và sẽ báo rõ khi tài liệu hiện có chưa đủ căn cứ."
    ),
    "capabilities": (
        "Bạn có thể tải tài liệu (.pdf, .docx, .xlsx, .csv, .md, .txt) vào kho tri thức, đặt câu hỏi tra cứu, "
        "so sánh phiên bản, kiểm tra mâu thuẫn hoặc dùng lệnh \"/\" để gọi kỹ năng chuyên ngành. Với nội dung không "
        "có trong tài liệu, tôi sẽ báo rõ thay vì suy đoán."
    ),
    "empty_or_punctuation": (
        "Tôi chưa thấy nội dung câu hỏi cụ thể. Bạn hãy nhập câu hỏi hoặc yêu cầu rõ hơn về tài liệu cần tra cứu nhé."
    ),
}

_SIMPLE_QUESTION_STARTS = (
    "what ", "which ", "who ", "where ", "when ", "why ", "how ",
    "does ", "do ", "is ", "are ", "can ", "could ",
)
_VN_QUESTION_PATTERNS = (
    "bao lau", "la gi", "la bao nhieu", "bao nhieu", "khi nao", "luc nao",
    "o dau", "nhu the nao", "the nao", "ai la", "ai duoc", "ai chiu",
    "co duoc", "co phai", "co dung", "quy dinh khong", "hop le khong",
    "dieu kien", "thoi han", "muc phat", "han muc",
    "quy dinh gi", "quy dinh nhu", "la may", "may ngay", "may gio",
    "theo dieu", "theo nghi dinh", "theo luat", "theo quy che", "theo noi quy",
    "theo hop dong", "trong tai lieu", "bang nao", "mau so",
    "cho toi biet", "cho biet", "cho em biet", "cho minh biet", "hay cho biet",
    "tra cuu", "tom tat", "neu ro", "liet ke", "thong tin ve",
    "duoc khong", "ai duyet", "gom nhung", "nhung ai", "nhung gi", "xin hoi",
)
_COMPLEX_ACTION_TERMS = frozenset({
    "review", "analyze", "analyse", "compare", "assess", "evaluate",
    "design", "produce", "create", "build", "implement", "implementation", "plan",
    "planning", "dependency", "dependencies", "risk", "risks", "concern",
    "concerns", "obligation", "obligations", "audit", "identify", "propose",
    "recommend",
})
_COMPLEX_ACTION_PHRASES = (
    "ra soat", "phan tich", "so sanh", "doi chieu", "danh gia", "thiet ke",
    "lap ke hoach", "phu thuoc", "rui ro", "quan ngai", "nghia vu",
    "xay dung", "de xuat", "xac dinh", "trien khai", "kiem tra mau thuan",
)


def _normalize_intent_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
    without_marks = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def product_help_response(message: str) -> tuple[str, str] | None:
    """Return a deterministic response for a small exact set of product intents."""

    normalized = _normalize_intent_text(message)
    if not normalized and str(message or "").strip():
        return "empty_or_punctuation", _RESPONSES["empty_or_punctuation"]
    for intent, phrases in _INTENT_RESPONSES.items():
        if normalized in phrases:
            return intent, _RESPONSES[intent]
    return None


_LIB_OBJECT = re.compile(r"\b(tai lieu|van ban|file|tep|nguon|cau tra loi)\b")
_LIB_ASK = re.compile(r"\b(nhung|gi|nao|liet ke|danh sach|bao nhieu)\b")
_LIB_PLACE = re.compile(r"\b(kho|thu vien|da tai|dang co|hien co|liet ke|danh sach|he thong co)\b")
_LIB_CONTENT_LEAD = re.compile(
    r"\b(dua tren|dua vao|can cu|theo (?:cac |nhung )?(?:tai lieu|van ban|quy che|noi quy|hop dong|bao cao|file|tep)|"
    r"phan tich|so sanh|tom tat|doanh thu|loi nhuan|chinh sach|phu cap|luong|thuong|dieu kien|quy trinh|muc phat|nghi phep|cam ket|sla|bao hiem)\b"
)
_LIB_DIRECT_LIST = re.compile(
    r"\b(?:liet ke|danh sach)\b.{0,35}\b(?:tai lieu|van ban|file|tep|nguon|cau tra loi)\b"
    r"|\bbao nhieu\s+(?:tai lieu|van ban|file|tep|nguon)\b"
    r"|\b(?:nhung|cac)\s+(?:tai lieu|van ban|file|tep|nguon|cau tra loi)\s+(?:gi|nao)\b"
    r"|\b(?:tai lieu|van ban|file|tep|nguon|cau tra loi)\s+(?:nao|gi)\s+(?:trong kho|da tai|dang co|hien co)\b"
    r"|\b(?:kho|thu vien|he thong)\b.{0,45}\b(?:tai lieu|van ban|file|tep|nguon|cau tra loi)\b"
)
_ENUM_PARTS = re.compile(r"(?:^|\s)(?:\(\s*[1-9]\s*\)|[1-9]\))\s+")


def is_library_question(message: str) -> bool:
    """Câu hỏi về chính kho tài liệu ("kho đang có những tài liệu gì"), không phải về nội dung tài liệu.
    V9: loại trừ hoàn toàn câu dẫn nhập hỏi nội dung ("Dựa trên các tài liệu hiện có, hãy cho biết..."), câu nhiều ý đánh số."""
    t = _normalize_intent_text(message)
    if not t or len(t) > 120 or message.count("?") >= 2 or _ENUM_PARTS.search(message):
        return False
    if " ve " in f" {t} " or _LIB_CONTENT_LEAD.search(t):
        return False
    return bool(
        _LIB_OBJECT.search(t)
        and _LIB_ASK.search(t)
        and _LIB_PLACE.search(t)
        and _LIB_DIRECT_LIST.search(t)
    )


def library_answer(rows: list[dict], doc_type_labels: dict[str, str]) -> str:
    """Danh sách tài liệu thật trong phạm vi hỏi, đọc từ kho (không gọi mô hình)."""
    if not rows:
        return "Kho chưa có tài liệu nào trong phạm vi này. Hãy tải tài liệu lên rồi hỏi về nội dung của chúng."
    lines = [f"Kho có **{len(rows)} tài liệu**:", ""]
    for i, r in enumerate(sorted(rows, key=lambda x: str(x.get("source_name", "")).lower()), 1):
        kind = doc_type_labels.get(r.get("doc_type") or "", "")
        meta = ", ".join(x for x in (kind, f"{r.get('chunk_count', 0)} đoạn") if x)
        lines.append(f"{i}. **{r.get('source_name')}** ({meta})")
    lines += ["", "Bạn có thể hỏi về nội dung của bất kỳ tài liệu nào ở trên, hoặc gõ \"/\" để chọn một kỹ năng."]
    return "\n".join(lines)


def is_simple_project_question(message: str, domains: Iterable[str]) -> bool:
    """Conservatively recognize a single factual question for grounded RAG.

    WORK_PACK_ROUTING fix: nhận diện câu hỏi tra cứu 1 ý tiếng Việt kể cả khi kết thúc
    bằng dấu chấm '.' hoặc chạm tối đa 2 từ khóa lĩnh vực liên quan (khi câu gọn và không
    chứa hành động phân tích/so sánh/lập kế hoạch nhiều bước).
    """
    normalized = _normalize_intent_text(message)
    if not normalized:
        return False
    question_part = message.split("[Ảnh đính kèm", 1)[0].rstrip()
    q_norm = _normalize_intent_text(question_part) or normalized
    if _COMPLEX_ACTION_TERMS.intersection(q_norm.split()) or any(
        phrase in q_norm for phrase in _COMPLEX_ACTION_PHRASES
    ):
        return False
    # Chặn câu hỏi đa vế rõ rệt (từ 3 dấu hỏi trở lên, cấu trúc đánh số (1)...(2), hoặc câu quá dài)
    unique_domains = set(domains)
    if message.count("?") >= 3 or len(_ENUM_PARTS.findall(message)) >= 2 or len(normalized) > 280:
        return False
    # 2 dấu hỏi chỉ tách luồng phức tạp khi chạm nhiều lĩnh vực khác nhau; cùng 1 chủ đề gọn vẫn đi nhánh nhanh
    if message.count("?") >= 2 and (len(unique_domains) >= 2 or len(normalized) > 240):
        return False
    question_form = (
        question_part.endswith("?")
        or q_norm.startswith(_SIMPLE_QUESTION_STARTS)
        or any(pat in q_norm for pat in _VN_QUESTION_PATTERNS)
    )
    if not question_form:
        return False
    return True
