from __future__ import annotations
from app.core.citations import strip_unauthorized_citations, validate_citations
from app.core.structured_output import is_placeholder_answer, parse_answer_json
from app.core.types import Task, TaskResult, SourceChunk, RunMetrics
from app.research.registry import profile
from app.core.answer_checks import IMG_MARK, finish, unsupported_articles, unsupported_quantities
from app.research.vanilla import REPLY_LANGUAGE_HINT, render_evidence, sanitize_includes

# Ô chat sản phẩm (21/11): tác tử con thấy câu hỏi gốc (dữ kiện của trường hợp, chữ trong ảnh) và chép số nguyên văn; thực nghiệm giữ prompt cũ.
PRODUCT_WORKER_HINT = (
    "QUY TẮC: Viết tiếng Việt. Mọi con số, mốc năm, tỷ lệ chép nguyên văn từ EVIDENCE, không ước đoán. "
    "Liệt kê đủ mọi điểm a), b), c)… của điều khoản liên quan, không thêm ý ngoài điều khoản. Ghi đúng số Điều, khoản. "
    "Khi phải tính toán, KHÔNG tự tính: viết phép tính với số cụ thể trong dấu [[= ... ]] (chỉ số, + - * / và ngoặc, 150% viết 1.5), "
    "hệ thống tự thay bằng kết quả. Dữ kiện trong USER_REQUEST (kể cả phần sau dấu \"" + IMG_MARK + "\" là chữ trong ảnh) là trường hợp "
    "cần xét, không phải bằng chứng: đối chiếu từng dữ kiện với ngưỡng, điều kiện trong EVIDENCE, viết rõ phép so sánh rồi kết luận."
)


def _extract_json(text: str) -> dict:
    return parse_answer_json(text)

async def execute_task(provider, task: Task, evidence: list[SourceChunk], metrics: RunMetrics, reply_language: str | None = None,
                       upstream: list[TaskResult] | None = None, product: bool = False, user_request: str | None = None) -> TaskResult:
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
    evidence_text = "\n\n".join(render_evidence(c) if product else f"[{c.chunk_id}] {c.text}" for c in evidence)
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
    if product:
        if user_request:
            user = f"[USER_REQUEST]{user_request[:2500]}[/USER_REQUEST]\n" + user
        user += "\n\n" + PRODUCT_WORKER_HINT
    elif reply_language in REPLY_LANGUAGE_HINT:
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
    if product:
        cleaned = strip_unauthorized_citations(answer, set(valid), set(raw_citations) | {c.chunk_id for c in evidence})
        answer, removed_include = sanitize_includes(cleaned)
        if removed_include or cleaned != str(obj.get("answer") or ""):
            if status == "COMPLETE":
                status = "PARTIAL"
            missing.append("unverified citation or include removed")
    if product and answer:
        articles = unsupported_articles(answer, evidence_text)
        quantities = unsupported_quantities(answer, evidence_text)
        answer, bad = finish(answer, evidence_text)
        if bad or articles or quantities:
            answer = "Kh\u00f4ng \u0111\u1ee7 c\u0103n c\u1ee9 \u0111\u1ec3 x\u00e1c nh\u1eadn s\u1ed1 li\u1ec7u ho\u1eb7c \u0111i\u1ec1u kho\u1ea3n trong k\u1ebft qu\u1ea3."
            status = "PARTIAL"
            missing.append("unsupported number or article")
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
