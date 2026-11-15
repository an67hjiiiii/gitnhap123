from __future__ import annotations
from app.core.citations import validate_citations
from app.core.structured_output import is_placeholder_answer, parse_answer_json
from app.core.types import Task, TaskResult, SourceChunk, RunMetrics
from app.research.registry import profile
from app.research.vanilla import REPLY_LANGUAGE_HINT


def _extract_json(text: str) -> dict:
    return parse_answer_json(text)

async def execute_task(provider, task: Task, evidence: list[SourceChunk], metrics: RunMetrics, reply_language: str | None = None,
                       upstream: list[TaskResult] | None = None) -> TaskResult:
    if not evidence:
        return TaskResult(
            task_id=task.task_id,
            domain=task.domain,
            status="NO_EVIDENCE",
            answer="Chưa tìm thấy evidence phù hợp cho task này.",
            evidence_ids=[],
            citations=[],
            missing_information=["relevant evidence"],
        )
    p = profile(task.domain)
    evidence_text = "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in evidence)
    system = (
        f"WORKER. Role={p['name']}. Scope={p['scope']}. Exclusions={p['exclusions']}. "
        "Use only supplied evidence; if insufficient, return NO_EVIDENCE or PARTIAL. "
        "Return JSON only and cite only exact supplied chunk IDs."
    )
    # Kết quả nhiệm vụ tiền đề (chức năng phụ thuộc): để giữ nhất quán, không phải bằng chứng, không được trích dẫn.
    upstream_text = (
        "[UPSTREAM]Results of prerequisite tasks (keep consistent with them; they are not evidence, "
        "cite only EVIDENCE chunk IDs):\n"
        + "\n".join(f"- {u.task_id} ({u.domain}, {u.status}): {u.answer[:800]}" for u in upstream)
        + "[/UPSTREAM]\n"
    ) if upstream else ""
    user = (
        f"[DOMAIN]{task.domain}[/DOMAIN]\n[TASK]{task.goal}[/TASK]\n{upstream_text}[EVIDENCE]{evidence_text}[/EVIDENCE]\n"
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
    missing = [str(x) for x in obj.get("missing_information") or []]
    if invalid:
        status = "PARTIAL"
        missing.append("invalid citation locator(s) removed")
    if status == "COMPLETE" and not valid:
        status = "PARTIAL"
        missing.append("worker answer has no valid citation")
    answer = str(obj.get("answer") or "")
    if is_placeholder_answer(answer):
        answer = ""
        if status == "COMPLETE":
            status = "PARTIAL"
        missing.append("worker returned an empty answer")
    return TaskResult(
        task_id=task.task_id,
        domain=task.domain,
        status=status,
        answer=answer,
        evidence_ids=[c.chunk_id for c in evidence],
        citations=valid,
        invalid_citations=invalid,
        missing_information=missing,
    )
