from __future__ import annotations
import json
import re
from app.core.citations import validate_citations
from app.core.types import Task, TaskResult, SourceChunk, RunMetrics
from app.research.registry import profile


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else {"status":"PARTIAL","answer":text,"citations":[],"missing_information":[]}

async def execute_task(provider, task: Task, evidence: list[SourceChunk], metrics: RunMetrics) -> TaskResult:
    if not evidence:
        return TaskResult(
            task_id=task.task_id,
            domain=task.domain,
            status="NO_EVIDENCE",
            answer="Mình chưa tìm thấy thông tin cho phần này trong tài liệu đã tải lên. Bạn hãy tải thêm tài liệu liên quan đến phần này.",
            evidence_ids=[],
            citations=[],
            missing_information=["relevant evidence"],
        )
    p = profile(task.domain)
    evidence_text = "\n\n".join(f"[{c.chunk_id}] Tài liệu: {c.source_name or c.source_id or c.chunk_id}\n{c.text}" for c in evidence)
    system = (
        f"WORKER. Role={p['name']}. Scope={p['scope']}. Exclusions={p['exclusions']}. "
        "Chỉ dùng bằng chứng được cấp; chỉ trả JSON theo Schema, citations chỉ chứa chunk ID chính xác được cấp. "
        "Viết answer bằng tiếng Việt tự nhiên, tối đa 4 câu, khoảng 100 từ; chỉ dài hơn khi yêu cầu cần danh sách. "
        "Mỗi khẳng định từ tài liệu phải có citations. Diễn giải thay vì chép nguyên đoạn; "
        "dẫn nguồn bằng 'theo tài liệu <source name>', dùng tên ở dòng Tài liệu; nếu chỉ có ID thì giữ ID. "
        "Không tự tạo tên nguồn hay ID. Giữ nguyên tên kỹ thuật, mã, giá trị và locator. "
        "Thiếu thông tin: trả NO_EVIDENCE hoặc PARTIAL, nói rõ phần chưa tìm thấy "
        "và đề xuất đúng một bước tiếp theo cụ thể, không chỉ từ chối.\n"
        'Ví dụ 1 — Bằng chứng: [c1] Tài liệu: API.md; khóa giữ 24 giờ. Hỏi: Khóa giữ bao lâu?\n'
        '{"status":"COMPLETE","answer":"Khóa được giữ 24 giờ, theo tài liệu API.md.",'
        '"citations":["c1"],"missing_information":[]}\n'
        'Ví dụ 2 — Bằng chứng chỉ nói về thời hạn khóa. Hỏi: Giới hạn tải tệp là bao nhiêu?\n'
        '{"status":"NO_EVIDENCE","answer":"Mình chưa tìm thấy giới hạn tải tệp. '
        'Bạn hãy tải lên tài liệu quy định dung lượng tệp.","citations":[],"missing_information":["giới hạn tải tệp"]}'
    )
    user = (
        f"[DOMAIN]{task.domain}[/DOMAIN]\n[TASK]{task.goal}[/TASK]\n[EVIDENCE]{evidence_text}[/EVIDENCE]\n"
        'Schema: {"status":"COMPLETE|PARTIAL|NO_EVIDENCE","answer":"...",'
        '"citations":["chunk_id"],"missing_information":[]}'
    )
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
    missing = [str(x) for x in obj.get("missing_information") or []]
    if invalid:
        status = "PARTIAL"
        missing.append("invalid citation locator(s) removed")
    if status == "COMPLETE" and not valid:
        status = "PARTIAL"
        missing.append("worker answer has no valid citation")
    return TaskResult(
        task_id=task.task_id,
        domain=task.domain,
        status=status,
        answer=str(obj.get("answer") or ""),
        evidence_ids=[c.chunk_id for c in evidence],
        citations=valid,
        invalid_citations=invalid,
        missing_information=missing,
    )
