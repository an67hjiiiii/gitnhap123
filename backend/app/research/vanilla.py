from __future__ import annotations
from app.core.citations import validate_citations
from app.core.structured_output import is_placeholder_answer, parse_answer_json
from app.core.types import RunMetrics, SourceChunk, TaskResult


def _extract_json(text: str) -> dict:
    return parse_answer_json(text)


# Nhắc ngôn ngữ ở cuối prompt (mô hình nhỏ dễ trả lời theo ngôn ngữ của bằng chứng). Chỉ bật ở chế độ sản phẩm hoặc lượt Phân tích của Studio (reply_in_query_language); lượt nghiên cứu khác giữ prompt gốc.
REPLY_LANGUAGE_HINT = {
    "vi": 'NGÔN NGỮ: Viết trường "answer" hoàn toàn bằng tiếng Việt, kể cả khi bằng chứng là tiếng Anh. Trả lời gọn, tối đa khoảng 150 từ. Giữ nguyên tên kỹ thuật, mã, giá trị và chunk ID.',
    "en": 'LANGUAGE: Write the "answer" field in English. Keep it concise, at most about 150 words. Keep technical names, code, values and chunk IDs unchanged.',
}


async def answer_vanilla(provider, query: str, evidence: list[SourceChunk], metrics: RunMetrics, reply_language: str | None = None) -> TaskResult:
    if not evidence:
        return TaskResult(
            task_id="T1",
            domain="general",
            status="NO_EVIDENCE",
            answer="Không tìm thấy bằng chứng phù hợp trong nguồn đã nạp để trả lời yêu cầu này.",
            evidence_ids=[],
            citations=[],
            missing_information=["relevant evidence"],
        )

    evidence_text = "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in evidence)
    system = (
        "VANILLA_RAG_ANSWERER. Use only supplied evidence. Return JSON only. "
        "Every factual claim that comes from the corpus must be grounded by one or more exact chunk IDs. "
        "If evidence is insufficient, return PARTIAL or NO_EVIDENCE and do not invent citations. "
        "Write the user-facing natural-language answer in Vietnamese by default, regardless of query or evidence language. "
        "Preserve technical identifiers, API paths, class/function/field names, SQL identifiers, code blocks, literal values, "
        "source IDs, chunk IDs, and citation locators exactly; do not translate or mutate them."
    )
    user = (
        f"USER REQUEST:\n{query}\n\nEVIDENCE:\n{evidence_text}\n\n"
        'Schema: {"status":"COMPLETE|PARTIAL|NO_EVIDENCE","answer":"...",'
        '"citations":["chunk_id"],"missing_information":[]}'
    )
    if reply_language in REPLY_LANGUAGE_HINT:
        user += "\n\n" + REPLY_LANGUAGE_HINT[reply_language]
    grounded = getattr(provider, "generate_grounded", None)
    result = (
        await grounded(system=system, user=user, evidence_ids=[c.chunk_id for c in evidence])
        if callable(grounded)
        else await provider.generate(system=system, user=user)
    )
    metrics.add_usage(result.usage)
    obj = _extract_json(result.text)
    raw_citations = [str(x) for x in obj.get("citations") or []]
    valid, invalid = validate_citations(raw_citations, evidence)
    metrics.add_citations(valid, invalid)

    status = str(obj.get("status") or "PARTIAL").upper()
    answer = str(obj.get("answer") or "").strip()
    missing = [str(x) for x in obj.get("missing_information") or []]
    if invalid:
        status = "PARTIAL"
        missing.append("invalid citation locator(s) removed")
    if status == "COMPLETE" and not valid:
        status = "PARTIAL"
        missing.append("answer has no valid citation")
    if is_placeholder_answer(answer):
        answer = ""
        if status == "COMPLETE":
            status = "PARTIAL"
        missing.append("model returned an empty answer")

    if valid:
        answer = answer.rstrip() + "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in valid)

    return TaskResult(
        task_id="T1",
        domain="general",
        status=status,
        answer=answer,
        evidence_ids=[c.chunk_id for c in evidence],
        citations=valid,
        invalid_citations=invalid,
        missing_information=missing,
    )
