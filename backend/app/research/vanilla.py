from __future__ import annotations

from app.core.text_clean import strip_placeholder_tags

import json
import os
import re

from app.core.citations import validate_citations
from app.core.structured_output import is_placeholder_answer, parse_answer_json
from app.core.types import RunMetrics, SourceChunk, TaskResult


def _extract_json(text: str) -> dict:
    return parse_answer_json(text)


# Nhắc ngôn ngữ ở cuối prompt (mô hình nhỏ dễ trả lời theo ngôn ngữ của bằng chứng). Chỉ bật ở chế độ sản phẩm hoặc lượt Phân tích của Studio (reply_in_query_language); lượt nghiên cứu khác giữ prompt gốc.
REPLY_LANGUAGE_HINT = {
    "vi": 'NGÔN NGỮ: Viết trường "answer" hoàn toàn bằng tiếng Việt, kể cả khi bằng chứng là tiếng Anh. Tối đa 4 câu, khoảng 100 từ; chỉ dùng danh sách dài hơn khi yêu cầu cần. Giữ nguyên tên kỹ thuật, mã, giá trị và chunk ID.',
    "en": 'LANGUAGE: Write the "answer" field in English. Use at most 4 sentences, about 100 words; use a longer list only when requested. Keep technical names, code, values and chunk IDs unchanged.',
}


def _format_evidence_chunk(chunk: SourceChunk) -> str:
    header = f"[{chunk.chunk_id}] Tài liệu: {chunk.source_name or chunk.source_id or chunk.chunk_id}"
    version_line = chunk.provenance.get("version_line")
    if os.getenv("CHUNK_MODE", "").strip().lower() == "legal" and version_line:
        header += f"\nPhiên bản: {version_line}"
        location = str(chunk.provenance.get("section_path") or "").rsplit(" > ", 1)[-1]
        if re.match(r"Điều\s+\d+[a-zđ]?\s*[.:]", location, re.IGNORECASE):
            header += f"\nVị trí: {location}"
    return f"{header}\n{chunk.text}"


def _guard_evidence_text(chunk: SourceChunk) -> str:
    version_line = chunk.provenance.get("version_line")
    if os.getenv("CHUNK_MODE", "").strip().lower() == "legal" and version_line:
        return f"Tài liệu: {chunk.source_name}\nPhiên bản: {version_line}\n{chunk.text}"
    return chunk.text


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

    if all(c.provenance.get("version_unchanged") for c in evidence):
        sentences = []
        for old, new in zip(evidence[::2], evidence[1::2]):
            if (old.provenance.get("version_side") != "before"
                    or new.provenance.get("version_side") != "after"
                    or old.provenance.get("version_unit") != new.provenance.get("version_unit")):
                break
            sentences.append(
                f"Không đổi về nội dung: bản {old.provenance['version_label']} ghi '{old.provenance['version_excerpt']}', "
                f"bản {new.provenance['version_label']} ghi '{new.provenance['version_excerpt']}' "
                "(cùng giá trị sau chuẩn hóa).")
        else:
            if len(evidence) % 2 == 0 and sentences:
                citations = [c.chunk_id for c in evidence]
                metrics.add_citations(citations, [])
                return TaskResult(task_id="T1", domain="general", status="COMPLETE",
                    answer="\n".join(sentences) + "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in citations),
                    evidence_ids=citations, citations=citations)

    evidence_text = "\n\n".join(_format_evidence_chunk(c) for c in evidence)
    system = (
        "VANILLA_RAG_ANSWERER. Chỉ dùng bằng chứng được cấp. Chỉ trả JSON theo Schema. "
        "Mặc định viết answer bằng tiếng Việt (Vietnamese), tự nhiên, tối đa 4 câu, khoảng 100 từ; "
        "chỉ dài hơn khi yêu cầu cần danh sách. Mỗi khẳng định từ tài liệu phải có chunk ID chính xác trong citations. "
        "Diễn giải, không chép nguyên đoạn; dẫn nguồn trong câu bằng 'theo tài liệu <source name>', "
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
    if any(c.provenance.get("version_diff") for c in evidence):
        diff_instruction = ("\nĐây là bằng chứng từ bảng diff đã chuẩn hóa. Chỉ viết 1-2 câu tóm tắt các thay đổi, "
                 "nêu Điều/khoản và giá trị trước/sau; KHÔNG ghi chunk ID trong câu (ID chỉ đưa vào citations); "
                 "không chép lại bảng, bảng chi tiết do hệ thống tự thêm. Không suy diễn thay đổi ngoài bảng diff.")
        system += diff_instruction
        user += diff_instruction
        if all(c.provenance.get("version_unchanged") for c in evidence):
            user += ("\nHai đoạn là cùng nội dung sau chuẩn hóa đơn vị hoặc đổi số Điều. "
                     "Trả lời rõ 'không đổi về nội dung', trích cả hai phiên bản.")
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
    if is_placeholder_answer(answer):
        answer = ""
        if status == "COMPLETE":
            status = "PARTIAL"
        missing.append("model returned an empty answer")

    guard_notes: list[str] = []
    if checker is not None and answer:
        cited = [c for c in evidence if c.chunk_id in valid]
        cited_texts = [_guard_evidence_text(c) for c in cited]
        source_label = ", ".join(dict.fromkeys(
            c.source_name or c.source_id or c.chunk_id for c in (cited or evidence)
        ))
        checked = checker.guard(
            answer, status=status, evidence_texts=[_guard_evidence_text(c) for c in evidence],
            source_label=source_label, cited_texts=cited_texts, question=query,
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

    if os.getenv("VERSION_FILTER", "off").strip().lower() == "on" and answer:
        families = {}
        cited_families = {c.provenance.get("family_key") for c in evidence if c.chunk_id in valid}
        # Mọi đoạn đưa cho mô hình đều tính: mô hình có thể dùng bản chưa xác nhận mà không trích.
        for chunk in evidence:
            family = chunk.provenance.get("family_key")
            if family:
                families.setdefault(family, {})[chunk.source_id] = chunk.provenance.get("version_confirmed", False)
        for family, sources in sorted(families.items()):
            if family in cited_families and len(sources) >= 2 and not any(sources.values()):
                answer = answer.rstrip() + f"\n\nLưu ý: chưa xác nhận bản hiện hành của {family}."

    if any(c.provenance.get("version_diff") for c in evidence):
        from app.research.version_table import build_table
        table = build_table(evidence)
        if table:  # bảng dựng bằng mã từ mục diff; câu tóm tắt (đã qua guard) chỉ là lời dẫn
            lead = answer.strip() or "Các khác biệt tìm thấy giữa hai phiên bản:"
            answer = lead + "\n\n" + table
            if status == "NO_EVIDENCE":
                status = "PARTIAL"
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
