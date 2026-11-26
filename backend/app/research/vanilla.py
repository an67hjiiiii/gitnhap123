from __future__ import annotations
from app.core.answer_checks import IMG_MARK, check_product_evidence_claims, guard_no_evidence, normalize_status, strip_invalid_inline_citations
from app.core.citations import validate_citations
from app.core.structured_output import is_placeholder_answer, parse_answer_json
from app.core.types import RunMetrics, SourceChunk, TaskResult
from app.research.progress import answer_streamer, emit_validated_answer
from app.research.token_budget import fit_evidence_to_prompt_budget, resolve_product_num_ctx


def _extract_json(text: str) -> dict:
    return parse_answer_json(text)


# Nhắc ngôn ngữ ở cuối prompt (mô hình nhỏ dễ trả lời theo ngôn ngữ của bằng chứng). Chỉ bật ở chế độ sản phẩm hoặc lượt Phân tích của Studio (reply_in_query_language); lượt nghiên cứu khác giữ prompt gốc.
REPLY_LANGUAGE_HINT = {
    "vi": 'NGÔN NGỮ: Viết trường "answer" hoàn toàn bằng tiếng Việt, kể cả khi bằng chứng là tiếng Anh. Trả lời gọn, tối đa khoảng 150 từ. Giữ nguyên tên kỹ thuật, mã, giá trị và chunk ID.',
    "en": 'LANGUAGE: Write the "answer" field in English. Keep it concise, at most about 150 words. Keep technical names, code, values and chunk IDs unchanged.',
}

# Ô chat sản phẩm (product_mode) thay câu "tối đa 150 từ" bằng lời dặn trình bày có cấu trúc (21/11); thực nghiệm giữ REPLY_LANGUAGE_HINT.
PRODUCT_ANSWER_HINT = {
    "vi": (
        'NGÔN NGỮ VÀ TRÌNH BÀY: Viết trường "answer" hoàn toàn bằng tiếng Việt, định dạng Markdown, như một chuyên gia giải thích cho đồng nghiệp. '
        "Mở đầu bằng 1-2 câu trả lời thẳng vào câu hỏi. Nếu nội dung có nhiều ý: thêm tiêu đề ngắn dạng \"### ...\", gạch đầu dòng có **từ khóa in đậm**; "
        "các bước làm thì đánh số 1. 2. 3.; khi so sánh hoặc liệt kê nhiều mục có cùng thuộc tính (điều kiện, mức, thời hạn, phiên bản, người phụ trách) "
        "thì lập bảng Markdown có dòng tiêu đề (| Nội dung | ... |); nếu ghi nguồn thì đặt cột tên “Nguồn” chứa chunk ID, không đặt tên cột là “Chunk ID”. Câu hỏi đơn giản thì trả lời ngắn, không bày thêm. "
        "Nếu người dùng yêu cầu \"lập bảng\" hoặc \"bảng so sánh\" thì BẮT BUỘC trình bày bằng bảng Markdown, điền đủ mọi ô. "
        "Liệt kê các trường hợp, điều kiện thì liệt kê ĐỦ mọi điểm a), b), c)… có trong điều khoản tương ứng của bằng chứng, không thêm ý ngoài điều khoản đó. "
        "Mọi con số, mốc năm, tỷ lệ phải chép nguyên văn từ bằng chứng; không có thì nói không có, tuyệt đối không ước đoán. "
        "Khi phải tính toán, KHÔNG tự tính: viết từng phép tính với số cụ thể trong dấu [[= ... ]], ví dụ \"Lương giờ = [[= 12000000/26/8 ]] đồng\", "
        "chỉ dùng số, + - * / // và ngoặc (150% viết 1.5; \"cứ đủ N … được thêm\" dùng // lấy phần nguyên, ví dụ 12 + 6//5); hệ thống sẽ tự thay bằng kết quả, không viết lại kết quả sau dấu ]]. Nếu câu hỏi hỏi một số tiền, số ngày hay số lượng mà bằng chứng chỉ cho tỷ lệ, đơn giá hoặc mức theo ngày, PHẢI viết phép tính [[= ... ]] ra con số cuối cùng (ví dụ phạt 0,5%/ngày × 10 ngày × 120.000.000 → [[= 0.005*10*120000000 ]] đồng), không dừng ở tỷ lệ; câu hỏi có số lượng (4 ngày, 10 giờ, 200 ly) thì nhân số lượng đó với mức trong bằng chứng. Chỉ dùng con số của ĐÚNG chỉ số được hỏi: bằng chứng không có chỉ số đó (ví dụ hỏi người theo dõi mà chỉ có đơn hàng) thì nói tài liệu không có, không lấy số của chỉ số khác. "
        "Ghi căn cứ đúng số Điều, khoản như trong bằng chứng và đưa đủ mọi chunk ID đã viện dẫn vào trường \"citations\". Không viết mục \"Các chunk ID liên quan\", không nhắc mã nhiệm vụ (T1, T2). "
        "Tối đa khoảng 350 từ. Chỉ dùng thông tin có trong bằng chứng. Giữ nguyên tên kỹ thuật, mã, giá trị và chunk ID."
    ),
    "en": (
        'LANGUAGE AND FORMAT: Write the "answer" field in English as Markdown, like an expert explaining to a colleague. '
        "Open with 1-2 sentences that answer directly. For multi-part content add short \"### ...\" headings and bullets with **bold keywords**; "
        "number procedural steps; when comparing or listing items that share attributes, use a Markdown table with a header row; put chunk IDs in a column named Source. "
        "Keep simple answers short. At most about 350 words. Use only the evidence. Keep technical names, code, values and chunk IDs unchanged."
    ),
}


async def answer_vanilla(provider, query: str, evidence: list[SourceChunk], metrics: RunMetrics, reply_language: str | None = None,
                         product: bool = False, max_output_tokens: int | None = None, extra_hint: str | None = None,
                         role: dict | None = None, num_ctx: int | None = None,
                         request_timeout: float | None = None) -> TaskResult:
    safe_fallback = (
        "No relevant evidence was found in the loaded sources to answer this request."
        if reply_language == "en"
        else "Không tìm thấy bằng chứng phù hợp trong nguồn đã nạp để trả lời yêu cầu này."
    )
    if not evidence:
        if product:
            emit_validated_answer(safe_fallback)
        return TaskResult(
            task_id="T1",
            domain="general",
            status="NO_EVIDENCE",
            answer=safe_fallback,
            evidence_ids=[],
            citations=[],
            missing_information=["relevant evidence"],
        )

    system = (
        "VANILLA_RAG_ANSWERER. Use only supplied evidence. Return JSON only. "
        "Every factual claim that comes from the corpus must be grounded by one or more exact chunk IDs. "
        "If evidence is insufficient, return PARTIAL or NO_EVIDENCE and do not invent citations. "
        "Write the user-facing natural-language answer in Vietnamese by default, regardless of query or evidence language. "
        "Preserve technical identifiers, API paths, class/function/field names, SQL identifiers, code blocks, literal values, "
        "source IDs, chunk IDs, and citation locators exactly; do not translate or mutate them."
    )
    if product and role:  # câu đơn giản do chuyên gia ngành trả lời (ô chat sản phẩm); thực nghiệm không truyền role
        system += f" You answer as Role={role['name']}. Scope={role['scope']}."

    def _build_user(ev_text: str) -> str:
        body = (
            f"USER REQUEST:\n{query}\n\nEVIDENCE:\n{ev_text}\n\n"
            'Schema: {"status":"COMPLETE|PARTIAL|NO_EVIDENCE","answer":"...",'
            '"citations":["chunk_id"],"missing_information":[]}'
        )
        hints = PRODUCT_ANSWER_HINT if product else REPLY_LANGUAGE_HINT
        if reply_language in hints:
            body += "\n\n" + hints[reply_language]
        if product and extra_hint:  # bước chọn nguồn tri thức: cho phép bổ sung kiến thức chung có nhãn
            body += "\n\n" + extra_hint
        if product and IMG_MARK in query:  # ảnh dán vào ô chat: dữ kiện của trường hợp, không phải nguồn
            body += ("\n\nTRƯỜNG HỢP TRONG ẢNH: phần sau dấu \"" + IMG_MARK + "\" là dữ kiện người dùng đưa ra. Đối chiếu từng dữ kiện với "
                     "ngưỡng, điều kiện, thời hạn trong bằng chứng, viết rõ phép so sánh (ví dụ 0,72 < 1,0 nên không đạt) rồi kết luận. "
                     "Nếu quy định áp dụng có trong bằng chứng thì status là COMPLETE dù dữ kiện chỉ có trong ảnh.")
        return body

    budget_missing: list[str] = []
    effective_num_ctx: int | None = None
    if product:
        effective_num_ctx = num_ctx if num_ctx is not None else resolve_product_num_ctx()
        output_reserve = (
            max_output_tokens
            if max_output_tokens is not None
            else getattr(provider, "max_output_tokens", 700)
        )
        evidence, budget_info = fit_evidence_to_prompt_budget(
            evidence,
            system=system,
            prompt_without_evidence=_build_user(""),
            num_ctx=effective_num_ctx,
            output_reserve=output_reserve,
        )
        if budget_info["overflow"]:
            return TaskResult(
                task_id="T1",
                domain="general",
                status="PARTIAL",
                answer="Yêu cầu vượt quá giới hạn cửa sổ ngữ cảnh an toàn của mô hình (num_ctx); hệ thống từ chối gọi mô hình để tránh cắt mất nội dung câu hỏi.",
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
    grounded = getattr(provider, "generate_grounded", None)
    # câu trả lời có bảng dài hơn 700 token mặc định: ô chat cho giới hạn riêng (chỉ provider hỗ trợ)
    limit: dict = {}
    if product and max_output_tokens and getattr(provider, "supports_per_call_output_tokens", False):
        limit["max_output_tokens"] = max_output_tokens
    if product and effective_num_ctx is not None and getattr(provider, "supports_num_ctx", False):
        limit["num_ctx"] = effective_num_ctx
    if product and request_timeout is not None and getattr(provider, "supports_per_call_timeout", False):
        limit["timeout"] = request_timeout
    result = (
        await grounded(system=system, user=user, evidence_ids=[c.chunk_id for c in evidence], **limit, **answer_streamer(provider, buffered=bool(product)))
        if callable(grounded)
        else await provider.generate(system=system, user=user, **{k: v for k, v in limit.items() if k != "max_output_tokens"})
    )
    metrics.add_usage(result.usage)
    obj = _extract_json(result.text)
    raw_citations = [str(x) for x in obj.get("citations") or []]
    valid, invalid = validate_citations(raw_citations, evidence)
    metrics.add_citations(valid, invalid)

    answer = str(obj.get("answer") or "").strip()
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
            missing.append("answer has no valid citation")
    else:
        status = str(obj.get("status") or "PARTIAL").upper()
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
    status, answer, valid = guard_no_evidence(
        status,
        answer,
        valid,
        missing,
        query,
        safe_fallback,
        product=product,
        reply_language=reply_language,
    )

    if product and answer and status != "NO_EVIDENCE":  # hậu kiểm: máy tính thay phép tính, cảnh báo số/Điều không có trong nguồn (không áp cho thực nghiệm)
        allowed_inline = {c.chunk_id for c in evidence}
        answer, stripped_inline = strip_invalid_inline_citations(answer, allowed_inline)
        if stripped_inline:
            missing.append("unauthorized or unprompted inline citation(s) removed: " + ", ".join(stripped_inline[:6]))
            if status == "COMPLETE":
                status = "PARTIAL"
        status, answer, _, _ = check_product_evidence_claims(
            status, answer, evidence_text, query, missing, evidence_chunks=evidence
        )
    if valid and status != "NO_EVIDENCE":
        answer = answer.rstrip() + "\n\nNguồn: " + ", ".join(f"[{cid}]" for cid in valid)
    if product and answer.strip():
        emit_validated_answer(answer)

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
