"""Reviewer (Đợt 5 kế hoạch Văn phòng 3D, 23/11): đối chiếu từng ý của câu trả lời với đoạn tài liệu đã dùng.

Một lần gọi mô hình sau bước tổng hợp, chỉ ở ô chat sản phẩm khi câu hỏi đi đường lập kế hoạch (nhiều ý).
Không tự sửa câu trả lời: ý không thấy trong tài liệu được liệt kê ở cuối để người đọc kiểm tra.
Mô hình trả sai khuôn thì ghi lỗi và để nguyên câu trả lời, không coi là "đã duyệt".
Bật bằng PRODUCT_REVIEWER=on (mặc định tắt cho tới khi đo thời gian và chất lượng ở Đợt 8).
"""
from __future__ import annotations

import os

from app.core.structured_output import decode_structured_json
from app.core.types import RunMetrics

MAX_CLAIMS = 8
MAX_EVIDENCE_CHARS = 10000
REVIEW_OUTPUT_TOKENS = 600

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "maxItems": MAX_CLAIMS,
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "supported": {"type": "boolean"}},
                "required": ["claim", "supported"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

SYSTEM = (
    "REVIEWER. List the factual statements in ANSWER (at most 8, the most important first; skip greetings and advice). "
    "For each, set supported=true only if EVIDENCE states it or it follows by simple arithmetic from numbers in EVIDENCE; "
    "otherwise supported=false. Use only EVIDENCE, never outside knowledge. Copy each claim briefly in the language of ANSWER. "
    'Return JSON {"claims": [{"claim": "...", "supported": true}]}.'
)

NOTE = {
    "vi": "> **Reviewer:** các ý sau chưa thấy trong đoạn tài liệu đã dùng, hãy bấm vào nguồn để kiểm tra: ",
    "en": "> **Reviewer:** these points were not found in the document excerpts used; please check the sources: ",
}


def reviewer_enabled() -> bool:
    return os.getenv("PRODUCT_REVIEWER", "off").strip().lower() in {"1", "on", "true", "yes"}


async def review_answer(provider, answer: str, evidence_text: str, metrics: RunMetrics) -> dict:
    """Trả {"status": "ok"|"error"|"skipped", "checked", "unsupported": [...]}. Không ném lỗi ra ngoài."""
    structured = getattr(provider, "generate_structured", None)
    if not callable(structured) or not answer.strip() or not evidence_text.strip():
        return {"status": "skipped", "checked": 0, "unsupported": []}
    user = f"ANSWER:\n{answer}\n\nEVIDENCE:\n{evidence_text[:MAX_EVIDENCE_CHARS]}"
    kwargs = {"max_output_tokens": REVIEW_OUTPUT_TOKENS} if getattr(provider, "supports_per_call_output_tokens", False) else {}
    try:
        result = await structured(system=SYSTEM, user=user, response_schema=REVIEW_SCHEMA, **kwargs)
        metrics.add_usage(result.usage)
        claims = decode_structured_json(result.text).get("claims")
        if not isinstance(claims, list):
            raise ValueError("claims is not a list")
        claims = [c for c in claims if isinstance(c, dict) and str(c.get("claim", "")).strip()][:MAX_CLAIMS]
    except Exception as exc:  # mô hình lỗi/sai khuôn: để nguyên câu trả lời, ghi lý do
        return {"status": "error", "error": type(exc).__name__, "checked": 0, "unsupported": []}
    unsupported = [str(c["claim"]).strip() for c in claims if c.get("supported") is not True]
    return {"status": "ok", "checked": len(claims), "unsupported": unsupported}


def reviewer_revise_enabled() -> bool:
    """Reviewer trả bài để viết lại (23/11). Tắt bằng PRODUCT_REVIEWER_REVISE=off: khi đó chỉ ghi chú như trước."""
    return os.getenv("PRODUCT_REVIEWER_REVISE", "on").strip().lower() not in {"0", "off", "false", "no"}


def revision_note(unsupported: list[str]) -> str:
    items = "\n".join(f"- {c}" for c in unsupported[:MAX_CLAIMS])
    return (
        "REVIEWER FEEDBACK: the reviewer could not find these statements in the evidence:\n" + items + "\n"
        "Rewrite the answer: keep every statement that the task results support; correct a flagged statement only if the task "
        "results give the right fact; otherwise remove it or say the documents do not state it. Do not add new facts. "
        "Keep the same language, structure and citations."
    )


def annotate(answer: str, review: dict, language: str | None) -> str:
    if review.get("status") != "ok" or not review.get("unsupported"):
        return answer
    items = "; ".join(f"“{c}”" for c in review["unsupported"])
    return answer + "\n\n" + NOTE.get(language or "vi", NOTE["vi"]) + items
