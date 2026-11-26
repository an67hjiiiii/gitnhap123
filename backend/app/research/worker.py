from __future__ import annotations
from app.core.citations import validate_citations
from app.core.structured_output import is_placeholder_answer, parse_answer_json
from app.core.types import Task, TaskResult, SourceChunk, RunMetrics
from app.research.registry import profile
from app.core.answer_checks import IMG_MARK, check_product_evidence_claims, guard_no_evidence, normalize_status, strip_invalid_inline_citations
from app.research.token_budget import fit_evidence_to_prompt_budget, resolve_product_num_ctx
from app.research.vanilla import REPLY_LANGUAGE_HINT

# Ô chat sản phẩm (21/11): tác tử con thấy câu hỏi gốc (dữ kiện của trường hợp, chữ trong ảnh) và chép số nguyên văn; thực nghiệm giữ prompt cũ.
PRODUCT_WORKER_HINT = (
    "QUY TẮC: Viết tiếng Việt. Mọi con số, mốc năm, tỷ lệ chép nguyên văn từ EVIDENCE, không ước đoán. "
    "Liệt kê đủ mọi điểm a), b), c)… của điều khoản liên quan, không thêm ý ngoài điều khoản. Ghi đúng số Điều, khoản. "
    "Khi phải tính toán, KHÔNG tự tính: viết phép tính với số cụ thể trong dấu [[= ... ]] (chỉ số, + - * / // và ngoặc, 150% viết 1.5; \"cứ đủ N … được thêm\" dùng // để lấy phần nguyên, ví dụ 12 + 6//5), "
    "hệ thống tự thay bằng kết quả. Nếu câu hỏi hỏi một số tiền, số ngày hay số lượng mà bằng chứng chỉ cho tỷ lệ, đơn giá hoặc mức theo ngày, PHẢI viết phép tính [[= ... ]] ra con số cuối cùng (ví dụ phạt 0,5%/ngày × 10 ngày × 120.000.000 → [[= 0.005*10*120000000 ]] đồng), không dừng ở tỷ lệ; câu hỏi có số lượng (4 ngày, 10 giờ, 200 ly) thì nhân số lượng đó với mức trong bằng chứng. Chỉ dùng con số của ĐÚNG chỉ số được hỏi: bằng chứng không có chỉ số đó (ví dụ hỏi người theo dõi mà chỉ có đơn hàng) thì nói tài liệu không có, không lấy số của chỉ số khác. Dữ kiện trong USER_REQUEST (kể cả phần sau dấu \"" + IMG_MARK + "\" là chữ trong ảnh) là trường hợp "
    "cần xét, không phải bằng chứng: đối chiếu từng dữ kiện với ngưỡng, điều kiện trong EVIDENCE, viết rõ phép so sánh rồi kết luận."
)


def _extract_json(text: str) -> dict:
    return parse_answer_json(text)

async def execute_task(provider, task: Task, evidence: list[SourceChunk], metrics: RunMetrics, reply_language: str | None = None,
                       upstream: list[TaskResult] | None = None, product: bool = False, user_request: str | None = None,
                       extra_hint: str | None = None, num_ctx: int | None = None,
                       request_timeout: float | None = None) -> TaskResult:
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

    def _build_user(ev_text: str) -> str:
        body = (
            f"[DOMAIN]{task.domain}[/DOMAIN]\n[TASK]{task.goal}[/TASK]\n{upstream_text}[EVIDENCE]{ev_text}[/EVIDENCE]\n"
            'Schema: {"status":"COMPLETE|PARTIAL|NO_EVIDENCE","answer":"...",'
            '"citations":["chunk_id"],"missing_information":[]}'
        )
        if product:
            if user_request and user_request.strip() != task.goal.strip():
                # Đưa dữ kiện trường hợp/chữ ảnh làm ngữ cảnh tham chiếu sau [EVIDENCE], tránh chèn toàn bộ câu hỏi nhiều vế lên trước [TASK] (MA-04).
                body += f"\n[CASE_CONTEXT]{user_request[:1500]}[/CASE_CONTEXT]"
            body += "\n\n" + PRODUCT_WORKER_HINT
            if extra_hint:  # bước chọn nguồn tri thức: cho phép bổ sung kiến thức chung có nhãn
                body += "\n\n" + extra_hint
        elif reply_language in REPLY_LANGUAGE_HINT:
            body += "\n\n" + REPLY_LANGUAGE_HINT[reply_language]
        return body

    budget_missing: list[str] = []
    effective_num_ctx: int | None = None
    if product:
        effective_num_ctx = num_ctx if num_ctx is not None else resolve_product_num_ctx()
        evidence, budget_info = fit_evidence_to_prompt_budget(
            evidence,
            system=system,
            prompt_without_evidence=_build_user(""),
            num_ctx=effective_num_ctx,
            output_reserve=getattr(provider, "max_output_tokens", 700),
        )
        if budget_info["overflow"]:
            return TaskResult(
                task_id=task.task_id,
                domain=task.domain,
                status="PARTIAL",
                answer="Ngữ cảnh nhiệm vụ vượt quá giới hạn cửa sổ ngữ cảnh an toàn (num_ctx).",
                evidence_ids=[],
                citations=[],
                missing_information=["prompt_exceeds_num_ctx"],
            )
        if budget_info["trimmed_top"]:
            budget_missing.append("top_evidence_trimmed_to_num_ctx")
        elif budget_info["trimmed_trailing"]:
            budget_missing.append("trailing_evidence_trimmed_to_num_ctx")

    evidence_text = "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in evidence)
    user = _build_user(evidence_text)
    extra_opts: dict = {}
    if product and effective_num_ctx is not None and getattr(provider, "supports_num_ctx", False):
        extra_opts["num_ctx"] = effective_num_ctx
    if product and request_timeout is not None and getattr(provider, "supports_per_call_timeout", False):
        extra_opts["timeout"] = request_timeout
    grounded = getattr(provider, "generate_grounded", None)
    result = (
        await grounded(system=system, user=user, evidence_ids=[c.chunk_id for c in evidence], **extra_opts)
        if callable(grounded)
        else await provider.generate(system=system, user=user, **extra_opts)
    )
    metrics.add_usage(result.usage)
    obj = _extract_json(result.text)
    raw_citations = [str(x) for x in obj.get("citations") or []]
    valid, invalid = validate_citations(raw_citations, evidence)
    metrics.add_citations(valid, invalid)
    missing = [*budget_missing, *(str(x) for x in obj.get("missing_information") or [])]
    if product:
        status, status_normalized = normalize_status(obj.get("status"))
        model_no_evidence = status == "NO_EVIDENCE"
        if status_normalized:
            missing.append("noncanonical model status normalized")
        if obj.get("truncated") and status == "COMPLETE":
            status = "PARTIAL"
        if invalid:
            if not model_no_evidence:
                status = "PARTIAL"
            missing.append("invalid citation locator(s) removed")
        if status == "COMPLETE" and not valid:
            status = "PARTIAL"
            missing.append("worker answer has no valid citation")
        answer = str(obj.get("answer") or "").strip()
        if is_placeholder_answer(answer):
            answer = ""
            if status == "COMPLETE":
                status = "PARTIAL"
            missing.append("worker returned an empty answer")
        fallback_msg = (
            "No relevant evidence was found for this task."
            if reply_language == "en"
            else "Chưa tìm thấy evidence phù hợp cho task này."
        )
        status, answer, valid = guard_no_evidence(
            status,
            answer,
            valid,
            missing,
            user_request or task.goal,
            fallback_msg,
            product=True,
            reply_language=reply_language,
        )
        if answer and status != "NO_EVIDENCE":
            allowed_inline = {c.chunk_id for c in evidence}
            answer, stripped_inline = strip_invalid_inline_citations(answer, allowed_inline)
            if stripped_inline:
                missing.append("unauthorized or unprompted inline citation(s) removed: " + ", ".join(stripped_inline[:6]))
                if status == "COMPLETE":
                    status = "PARTIAL"
            status, answer, _, _ = check_product_evidence_claims(
                status, answer, evidence_text, user_request or task.goal, missing, evidence_chunks=evidence
            )
    else:
        status = str(obj.get("status") or "PARTIAL").upper()
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
