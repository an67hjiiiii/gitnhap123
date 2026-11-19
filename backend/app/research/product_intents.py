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
    },
    "thanks": {"thanks", "thank you", "cam on", "cam on ban"},
    "identity": {"ban la ai"},
    "capabilities": {"ban lam duoc gi", "toi co the hoi gi"},
}

_RESPONSES = {
    "greeting": (
        "Chào bạn! Tôi là trợ lý tài liệu CAP1_AI. Bạn có thể tải tài liệu vào "
        "Knowledge và đặt câu hỏi hoặc yêu cầu phân tích về kiến trúc/API, cơ sở "
        "dữ liệu và bảo mật."
    ),
    "thanks": "Rất vui được hỗ trợ. Bạn có thể hỏi về nội dung trong các tài liệu đã tải lên.",
    "identity": (
        "Tôi là trợ lý tài liệu CAP1_AI. Tôi trả lời câu hỏi về tài liệu bạn cung cấp "
        "và sẽ báo rõ khi nguồn hiện có không hỗ trợ kết luận."
    ),
    "capabilities": (
        "Bạn có thể tải tài liệu vào Knowledge, hỏi về nội dung trong nguồn hoặc yêu "
        "cầu phân tích kiến trúc, API, cơ sở dữ liệu và bảo mật. Với thông tin không "
        "có trong nguồn, tôi sẽ báo không tìm thấy evidence."
    ),
}

_SIMPLE_QUESTION_STARTS = (
    "what ", "which ", "who ", "where ", "when ", "why ", "how ",
    "does ", "do ", "is ", "are ", "can ", "could ",
)
_COMPLEX_ACTION_TERMS = frozenset({
    "review", "analyze", "analyse", "compare", "assess", "evaluate",
    "design", "produce", "create", "build", "implement", "implementation", "plan",
    "planning", "dependency", "dependencies", "risk", "risks", "concern",
    "concerns", "obligation", "obligations", "audit", "identify", "propose",
    "recommend",
})
_COMPLEX_ACTION_PHRASES = (
    "ra soat", "phan tich", "so sanh", "danh gia", "thiet ke",
    "lap ke hoach", "phu thuoc", "rui ro", "quan ngai", "nghia vu",
    "xay dung", "de xuat", "xac dinh", "trien khai",
)


def _normalize_intent_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
    without_marks = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def product_help_response(message: str) -> tuple[str, str] | None:
    """Return a deterministic response for a small exact set of product intents."""

    normalized = _normalize_intent_text(message)
    for intent, phrases in _INTENT_RESPONSES.items():
        if normalized in phrases:
            return intent, _RESPONSES[intent]
    return None


def is_simple_project_question(message: str, domains: Iterable[str]) -> bool:
    """Conservatively recognize a single factual question for grounded RAG.

    Routing requires a question form, at most one detected project domain, and
    no multi-step analysis/planning language. No single keyword or message
    length threshold selects the path.
    """

    normalized = _normalize_intent_text(message)
    if not normalized:
        return False
    question_form = message.rstrip().endswith("?") or normalized.startswith(
        _SIMPLE_QUESTION_STARTS
    )
    if not question_form or len(set(domains)) > 1:
        return False
    if _COMPLEX_ACTION_TERMS.intersection(normalized.split()) or any(
        phrase in normalized for phrase in _COMPLEX_ACTION_PHRASES
    ):
        return False
    return True
