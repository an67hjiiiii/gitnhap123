from __future__ import annotations

from app.core.text_clean import strip_placeholder_tags

import json
import re

from app.core.citations import validate_citations
from app.core.types import RunMetrics, SourceChunk, TaskResult


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {"status": "PARTIAL", "answer": text, "citations": [], "missing_information": []}
        return json.loads(m.group(0))


# Nhắc ngôn ngữ ở cuối prompt (mô hình nhỏ dễ trả lời theo ngôn ngữ của bằng chứng). Chỉ dùng cho chế độ sản phẩm.
REPLY_LANGUAGE_HINT = {
    "vi": 'NGÔN NGỮ: Viết trường "answer" hoàn toàn bằng tiếng Việt, kể cả khi bằng chứng là tiếng Anh. Tối đa 4 câu, khoảng 100 từ; chỉ dùng danh sách dài hơn khi yêu cầu cần. Giữ nguyên tên kỹ thuật, mã, giá trị và chunk ID.',
    "en": 'LANGUAGE: Write the "answer" field in English. Use at most 4 sentences, about 100 words; use a longer list only when requested. Keep technical names, code, values and chunk IDs unchanged.',
}


async def answer_vanilla(provider, query: str, evidence: list[SourceChunk], metrics: RunMetrics, reply_language: str | None = None, checker=None) -> TaskResult:
    if not evidence:
        return TaskResult(
            task_id="T1",
            domain="general",
            status="NO_EVIDENCE",
            answer="Mình chưa tìm thấy thông tin này trong các tài liệu đã tải lên. Bạn có thể tải thêm tài liệu liên quan hoặc hỏi cụ thể hơn (ví dụ nêu tên mục hoặc giá trị cần tìm), mình sẽ tra lại.",
            evidence_ids=[],
            citations=[],
            missing_information=["relevant evidence"],
        )

    evidence_text = "\n\n".join(f"[{c.chunk_id}] Tài liệu: {c.source_name or c.source_id or c.chunk_id}\n{c.text}" for c in evidence)
    system = (
        "VANILLA_RAG_ANSWERER. Chỉ dùng bằng chứng được cấp. Chỉ trả JSON theo Schema. "
        "Mặc định viết answer bằng tiếng Việt (Vietnamese), tự nhiên, tối đa 4 câu, khoảng 100 từ; "
        "chỉ dài hơn khi yêu cầu cần danh sách. Mỗi khẳng định từ tài liệu phải có chunk ID chính xác trong citations. "
        "Diễn giải, không chép nguyên đoạn; dẫn nguồn trong câu bằng 'theo tài liệu + tên tài liệu', "
        "dùng tên ở dòng Tài liệu, nếu chỉ có ID thì giữ ID. Không tự tạo tên nguồn hay ID. "
        "Thiếu thông tin: nói rõ phần chưa tìm thấy, trả PARTIAL hoặc NO_EVIDENCE, "
        "đề xuất đúng một bước tiếp theo cụ thể, không chỉ từ chối. "
        "Giữ nguyên tên kỹ thuật, API path, tên lớp/hàm/trường, SQL, mã, giá trị, source ID, chunk ID và locator.\n"
        'Schema: {"status":"COMPLETE|PARTIAL|NO_EVIDENCE","answer":"...",'
        '"citations":["chunk_id"],"missing_information":[]}\n'
        'Ví dụ 1 — Bằng chứng: [c1] Tài liệu: API.md; khóa giữ 24 giờ. Hỏi: Khóa giữ bao lâu?\n'
        '{"status":"COMPLETE","answer":"Khóa được giữ 24 giờ, theo tài liệu API.md.",'
        '"citations":["c1"],"missing_information":[]}\n'
        'Ví dụ 2 — Bằng chứng chỉ nói về thời hạn khóa. Hỏi: Giới hạn tải tệp là bao nhiêu?\n'
        '{"status":"NO_EVIDENCE","answer":"Mình chưa tìm thấy giới hạn tải tệp. '
        'Bạn hãy tải lên tài liệu quy định dung lượng tệp.","citations":[],"missing_information":["giới hạn tải tệp"]}'
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
    answer = strip_placeholder_tags(str(obj.get("answer") or "").strip())
    missing = [str(x) for x in obj.get("missing_information") or []]
    if invalid:
        status = "PARTIAL"
        missing.append("invalid citation locator(s) removed")
    if status == "COMPLETE" and not valid:
        status = "PARTIAL"
        missing.append("answer has no valid citation")

    guard_notes: list[str] = []
    if checker is not None and answer:
        cited = [c for c in evidence if c.chunk_id in valid]
        cited_texts = [c.text for c in cited]
        source_label = ", ".join(dict.fromkeys(
            c.source_name or c.source_id or c.chunk_id for c in (cited or evidence)
        ))
        checked = checker.guard(
            answer, status=status, evidence_texts=[c.text for c in evidence],
            source_label=source_label, cited_texts=cited_texts,
        )
        answer, guard_notes = checked.answer, checked.notes
        removed_claims = list(checked.removed_claims)
        replaced = any(n in guard_notes for n in {"ANSWER_REPLACED_BY_EXCERPT", "ANSWER_REPLACED_UNSUPPORTED"})
        if not replaced and status in {"COMPLETE", "PARTIAL"} and checker.needs_verification(query, answer):
            answer, verify_notes = await checker.verify(
                provider, answer, [c.text for c in evidence], metrics,
                source_label=source_label, cited_texts=cited_texts, removed_claims=removed_claims,
            )
            guard_notes = [*guard_notes, *verify_notes]
        if removed_claims:
            status = "PARTIAL"
            missing.extend("đã bỏ câu không có căn cứ: " + claim[:60] for claim in removed_claims)

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
        guard_notes=guard_notes,
    )
