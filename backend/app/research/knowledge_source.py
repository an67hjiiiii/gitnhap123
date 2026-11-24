"""Bước điều phối "chọn nguồn tri thức" (23/11, chỉ ô chat sản phẩm; thực nghiệm A/B/C không đi qua).

Mỗi việc lấy tri thức từ một trong ba nguồn:
- documents: chỉ tài liệu, có trích dẫn (câu hỏi gắn với tài liệu: "theo nội quy…", nêu tên tài liệu);
- general: kiến thức chung của mô hình, gắn nhãn rõ, không trích dẫn (không có tài liệu, hoặc tài liệu không nói tới);
- both: trả lời theo tài liệu, phần giải thích phổ thông tài liệu không có được bổ sung ở dòng "Kiến thức chung:".
Câu gắn với tài liệu mà tài liệu không có vẫn trả lời "tài liệu không nêu", không chuyển sang kiến thức chung.
"""
from __future__ import annotations

import re

from app.core.answer_checks import apply_calc, clean
from app.core.structured_output import parse_answer_json
from app.core.types import RunMetrics, TaskResult
from app.research.progress import answer_streamer

DOCUMENTS, GENERAL, BOTH = "documents", "general", "both"
GENERAL_MISSING = "answered from general knowledge, not from the user's documents"

_DOC_BOUND = re.compile(
    r"\b(theo|trong|căn cứ|dựa (vào|trên)|đối chiếu)\s+(các\s+|bản\s+|file\s+)?"
    r"(tài liệu|văn bản|nội quy|quy chế|quy định của công ty|hợp đồng|kế hoạch|hướng dẫn|báo cáo|đặc tả|biên bản|chính sách|tệp|bảng)"
    r"|\btài liệu (này|đã (tải|gửi)|của (tôi|công ty|mình))"
    r"|\b(according to|based on|in) (the|this|my) (document|file|contract|policy|report|plan|manual|spec)",
    re.I,
)
_EXPLAIN = re.compile(r"\b(vì sao|tại sao|giải thích|là gì|nghĩa là gì|why|explain|what is)\b", re.I)

BOTH_HINT = (
    "NGUỒN TRI THỨC: trả lời phần có trong EVIDENCE như quy tắc trên. Nếu một phần câu hỏi là kiến thức phổ thông (giải thích lý do, khái niệm) "
    "mà EVIDENCE không có, được bổ sung ngắn ở một đoạn riêng mở đầu đúng bằng \"Kiến thức chung:\" (không trích dẫn, không gán cho tài liệu). "
    "Không dùng kiến thức chung cho số liệu, quy định, thời hạn của tài liệu."
)

_LABEL = {
    ("vi", False): "**Kiến thức chung** (bạn chưa gửi tài liệu cho câu này, trả lời theo hiểu biết của mô hình, nên kiểm tra lại với nguồn tin cậy):",
    ("vi", True): "Tài liệu bạn gửi không có thông tin này. **Theo kiến thức chung** (không từ tài liệu, nên kiểm tra lại):",
    ("en", False): "**General knowledge** (no documents were provided; answered from the model's knowledge, please verify):",
    ("en", True): "Your documents do not contain this information. **From general knowledge** (not from your documents, please verify):",
}


def doc_bound(query: str, named_documents: list[str] | None = None) -> bool:
    """Câu hỏi gắn với tài liệu: chỉ được trả lời từ tài liệu."""
    return bool(named_documents) or bool(_DOC_BOUND.search(query or ""))


def choose_source(query: str, evidence_count: int, *, bound: bool) -> str:
    if bound:
        return DOCUMENTS
    if evidence_count == 0:
        return GENERAL
    return BOTH if _EXPLAIN.search(query or "") else DOCUMENTS


def label(reply_language: str | None, had_documents: bool) -> str:
    return _LABEL[("en" if reply_language == "en" else "vi", had_documents)]


async def answer_general(provider, question: str, metrics: RunMetrics, *, task_id: str = "T1", domain: str = "general",
                         role: str = "General Assistant", reply_language: str | None = None, had_documents: bool = False,
                         max_output_tokens: int | None = None, user_request: str | None = None, stream: bool = False) -> TaskResult:
    """Trả lời bằng kiến thức chung của mô hình. Nhãn do mã gắn (không để mô hình tự quyết), không có trích dẫn."""
    english = reply_language == "en"
    system = (
        f"GENERAL_KNOWLEDGE_ANSWERER. Role={role}. The user's documents do not cover this question, so answer from well-established "
        "general knowledge. Be accurate and concise. If a fact is uncertain, depends on country or may have changed recently "
        "(laws, prices, versions), say so briefly instead of guessing. Never invent document citations, article numbers or exact figures. "
        "Do not say the answer comes from the user's documents. Do not mention internal task IDs. "
        + ("Write the answer in English." if english else "Viết câu trả lời bằng tiếng Việt, kể cả khi câu hỏi hoặc mục tiêu việc viết bằng tiếng Anh.")
    )
    context = f"USER REQUEST (full question, for context):\n{user_request[:2500]}\n\n" if user_request and user_request != question else ""
    user = (
        f"{context}QUESTION TO ANSWER:\n{question}\n\n"
        + ("Write in English as Markdown. " if english else "Viết bằng tiếng Việt, dạng Markdown. ")
        # đo 23/11: prompt ép tiêu đề/mục làm mô hình 4B tự thêm chi tiết bịa ("thủ đô Úc là Sydney… theo Luật…"); câu đơn giản phải ngắn
        + ("Match the length to the question: a simple factual question gets 1-3 plain sentences with NO headings and no extra facts "
           "(population, laws, history) the user did not ask for. Only multi-part, how-to, comparison or planning requests get '### ' headings, "
           "numbered steps or a Markdown table (at most about 300 words). Code goes in fenced code blocks. "
           "Any number that needs calculating must be written ONLY as [[= expression ]] (digits, + - * / // and parentheses; powers as repeated "
           "multiplication, e.g. 100*1.06*1.06), also in the opening sentence; never write a computed result yourself, the system replaces it.")
        + ' Return JSON {"answer": "<Markdown answer>"}.'
    )
    structured = getattr(provider, "generate_structured", None)
    limit_ok = max_output_tokens is not None and getattr(provider, "supports_per_call_output_tokens", False)
    if callable(structured) and limit_ok:
        result = await structured(system=system, user=user, response_schema={"type": "object", "properties": {"answer": {"type": "string"}},
                                                                             "required": ["answer"], "additionalProperties": False},
                                  max_output_tokens=max_output_tokens, **(answer_streamer(provider) if stream else {}))
    else:
        result = await provider.generate(system=system, user=user)
    metrics.add_usage(result.usage)
    text = str(parse_answer_json(result.text).get("answer") or "").strip() or result.text.strip()
    text = apply_calc(clean(text))
    if not text:
        return TaskResult(task_id=task_id, domain=domain, status="NO_EVIDENCE", answer="", missing_information=["general answer was empty"],
                          source=GENERAL)
    return TaskResult(task_id=task_id, domain=domain, status="COMPLETE", answer=f"{label(reply_language, had_documents)}\n\n{text}",
                      missing_information=[GENERAL_MISSING], source=GENERAL)
