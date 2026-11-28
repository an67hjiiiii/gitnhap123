from __future__ import annotations
import re
from app.core.citations import resolve_citations, validate_citations
from app.core.structured_output import is_placeholder_answer, parse_answer_json
from app.core.types import Task, TaskResult, SourceChunk, RunMetrics
from app.research.registry import active_domains, profile, use_pack
from app.core.answer_checks import (
    IMG_MARK,
    apply_calc_with_values,
    check_product_evidence_claims,
    detect_unanchored_entities,
    guard_no_evidence,
    is_task_topic_unanchored,
    normalize_status,
    strip_invalid_inline_citations,
)
from app.research.token_budget import fit_evidence_to_prompt_budget, resolve_product_num_ctx
from app.research.vanilla import REPLY_LANGUAGE_HINT

_REFUSAL_PHRASES = (
    "không có thông tin",
    "không được cung cấp",
    "không được đề cập",
    "không đề cập",
    "không quy định",
    "không cung cấp",
    "không tìm thấy",
    "không có dịch vụ",
    "không nêu",
    "không áp dụng",
    "chưa có thông tin",
    "không có trong tài liệu",
    "không có trong hợp đồng",
    "không đủ căn cứ",
)


def _is_pure_refusal(answer: str) -> bool:
    """Trả True nếu mọi câu nội dung trong câu trả lời của worker đều chỉ là xác nhận tài liệu không có thông tin."""
    import re
    cleaned = re.sub(r"(?im)^\s*\*?\*?Nguồn\*?\*?\s*:.*$", "", answer or "").strip()
    cleaned = re.sub(r"\[src_[0-9a-f]+_c\d+\]", "", cleaned)
    cleaned = re.sub(r"[*_`]+", "", cleaned)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", cleaned) if len(s.strip()) >= 8]
    if not sents:
        return False
    return all(any(p in s.casefold() for p in _REFUSAL_PHRASES) for s in sents)

# Ô chat sản phẩm (21/11): tác tử con thấy câu hỏi gốc (dữ kiện của trường hợp, chữ trong ảnh) và chép số nguyên văn; thực nghiệm giữ prompt cũ.
PRODUCT_WORKER_HINT = (
    "QUY TẮC: Viết tiếng Việt. CHỈ trả lời đúng phần việc trong [TASK] của riêng bạn, KHÔNG tự trả lời các ý khác thuộc [USER_REQUEST] nằm ngoài [TASK]. "
    "Nếu [TASK] hỏi từ 2 chỉ số trở lên (vd. X và Y), PHẢI nêu rõ giá trị RIÊNG cho từng chỉ số (X = ..., Y = ...), tuyệt đối không bỏ sót chỉ số thứ 2 hay gộp chung 1 số. "
    "Mọi con số, mốc năm, tỷ lệ chép nguyên văn từ EVIDENCE, không ước đoán. "
    "Liệt kê đủ mọi điểm a), b), c)… của điều khoản liên quan, không thêm ý ngoài điều khoản. "
    "Ghi đúng tên mục/số Điều như nguyên văn trong EVIDENCE (chỉ viết 'Điều N' khi EVIDENCE thực sự ghi 'Điều N'; nếu ghi '1.', '2.' thì viết 'Mục 1', 'Mục 2'). "
    "QUY TẮC TÍNH TOÁN (BẮT BUỘC): TUYỆT ĐỐI KHÔNG tự nhẩm số kết quả ở bất kỳ dòng nào (kể cả câu mở đầu) — luôn đặt thẳng phép tính vào [[= ... ]] ngay từ câu đầu tiên: "
    "(1) NHÂN ĐỦ SỐ LƯỢNG: câu hỏi cho N đơn vị (vd. mua thêm 20 tài khoản × 120.000, 12 nhân viên × 2.800.000, 15 tín chỉ × 950.000) PHẢI nhân đủ N với đơn giá trong [[= ... ]] (vd. [[= 20 * 120000 ]]), KHÔNG dừng ở đơn giá 1 đơn vị; "
    "(2) GIỮ NGUYÊN DẤU % trong [[= ... ]] (vd. [[= 0.5% * 10 * 240000000 ]], [[= 12 * 2800000 * (1 - 15%) ]], [[= 120% * 15 * 950000 ]]); "
    "(3) NGƯỠNG MIỄN & BƯỚC NHẢY: trừ ngưỡng trước ([[= (5 - 2) * 150000 ]]); nếu tính theo mỗi bước nhảy B (vd. mỗi 0,5 kg vượt thêm) phải chia B ([[= 28000 + ((3.5 - 2) / 0.5) * 4500 ]]); 'đủ mỗi K năm' dùng // ([[= 12 + (8 // 4) * 1 ]]). "
    "KHÔNG đặt chữ/biến trong [[= ... ]] và KHÔNG viết lặp '= kết quả' sau dấu ]]. "
    "Đánh giá status và missing_information CHỈ dựa trên phạm vi [TASK] của riêng bạn: nếu [TASK] đã đủ bằng chứng thì đặt status=\"COMPLETE\" và missing_information=[]. "
    "CHỐNG ĐÁNH TRÁO KHÁI NIỆM & ĐIỀU KHOẢN: TUYỆT ĐỐI KHÔNG lấy mức phạt, giá gói khám hay phụ cấp của mục A trả lời thay cho mục B không tồn tại trong EVIDENCE (vd. không lấy gói khám tổng quát GK-NC làm giá MRI 3.0 Tesla, không lấy phạt chậm tiến độ làm phạt rò rỉ dữ liệu Nghị định 13). "
    "Nếu EVIDENCE không có đúng chủ đề/dịch vụ/văn bản trong [TASK], BẮT BUỘC đặt status=\"NO_EVIDENCE\", citations=[], và nói rõ tài liệu không có thông tin. "
    "Dữ kiện trong USER_REQUEST (kể cả phần sau dấu \"" + IMG_MARK + "\" là chữ trong ảnh) là trường hợp "
    "cần xét, không phải bằng chứng: đối chiếu từng dữ kiện với ngưỡng, điều kiện trong EVIDENCE, viết rõ phép so sánh rồi kết luận."
)


def _extract_json(text: str) -> dict:
    return parse_answer_json(text)

async def execute_task(provider, task: Task, evidence: list[SourceChunk], metrics: RunMetrics, reply_language: str | None = None,
                       upstream: list[TaskResult] | None = None, product: bool = False, user_request: str | None = None,
                       extra_hint: str | None = None, num_ctx: int | None = None,
                       request_timeout: float | None = None, keep_alive: str | int | float | None = None) -> TaskResult:
    if not evidence:
        fallback_empty = (
            "No relevant evidence was found for this task."
            if reply_language == "en"
            else "Chưa tìm thấy evidence phù hợp cho task này."
        )
        return TaskResult(
            task_id=task.task_id,
            domain=task.domain,
            status="NO_EVIDENCE",
            answer=fallback_empty,
            evidence_ids=[],
            citations=[],
            missing_information=["relevant evidence"],
        )
    if task.domain in active_domains():
        p = profile(task.domain)
    elif task.domain in {"security", "database", "api_architecture", "general"}:
        with use_pack("software"):
            p = profile(task.domain)
    else:
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

    def _build_user(ev_text: str, *, include_warnings: bool = True) -> tuple[str, list[str], bool]:
        body = (
            f"[DOMAIN]{task.domain}[/DOMAIN]\n[TASK]{task.goal}[/TASK]\n{upstream_text}[EVIDENCE]{ev_text}[/EVIDENCE]\n"
            'Schema: {"status":"COMPLETE|PARTIAL|NO_EVIDENCE","answer":"...",'
            '"citations":["chunk_id"],"missing_information":[]}'
        )
        unanchored_ent: list[str] = []
        topic_unanch = False
        if product:
            if user_request and user_request.strip() != task.goal.strip():
                # Đưa dữ kiện trường hợp/chữ ảnh làm ngữ cảnh tham chiếu sau [EVIDENCE], tránh chèn toàn bộ câu hỏi nhiều vế lên trước [TASK] (MA-04).
                body += f"\n[CASE_CONTEXT]{user_request[:1500]}[/CASE_CONTEXT]"
            body += "\n\n" + PRODUCT_WORKER_HINT
            if include_warnings and ev_text:
                unanchored_ent = detect_unanchored_entities(task.goal, ev_text)
                topic_unanch = is_task_topic_unanchored(task.goal, ev_text)
                if unanchored_ent:
                    body += (
                        "\n\n[CẢNH BÁO ĐỐI CHIẾU TỪ KHÓA]: Các thực thể/văn bản sau có trong [TASK] nhưng XUẤT HIỆN 0 LẦN trong toàn bộ EVIDENCE: "
                        + ", ".join(unanchored_ent)
                        + ". TUYỆT ĐỐI KHÔNG gán giá dịch vụ/mức phạt của hạng mục khác thay cho các thực thể vắng mặt này; nếu [TASK] hỏi chính về chúng, PHẢI trả status=\"NO_EVIDENCE\" và citations=[]."
                    )
                elif topic_unanch:
                    body += (
                        "\n\n[CẢNH BÁO ĐỐI CHIẾU CHỦ ĐỀ]: Các từ khóa chủ đề chính trong [TASK] không xuất hiện trong bất kỳ đoạn EVIDENCE nào ở trên. "
                        "Nếu EVIDENCE thực sự không đề cập đến nội dung này, BẮT BUỘC đặt status=\"NO_EVIDENCE\", citations=[], và nói rõ tài liệu không có thông tin; "
                        "TUYỆT ĐỐI không tự tính ra con số mới hay lấy ngày ban hành / mức phí khác gán thay thế!"
                    )
            if extra_hint:  # bước chọn nguồn tri thức: cho phép bổ sung kiến thức chung có nhãn
                body += "\n\n" + extra_hint
        elif reply_language in REPLY_LANGUAGE_HINT:
            body += "\n\n" + REPLY_LANGUAGE_HINT[reply_language]
        return body, unanchored_ent, topic_unanch

    budget_missing: list[str] = []
    effective_num_ctx: int | None = None
    if product:
        effective_num_ctx = num_ctx if num_ctx is not None else resolve_product_num_ctx()
        base_prompt, _, _ = _build_user("", include_warnings=False)
        evidence, budget_info = fit_evidence_to_prompt_budget(
            evidence,
            system=system,
            prompt_without_evidence=base_prompt,
            num_ctx=effective_num_ctx,
            output_reserve=1100,
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
    user, unanchored_entities, topic_unanchored = _build_user(evidence_text, include_warnings=True)
    extra_opts: dict = {}
    if product and getattr(provider, "supports_per_call_output_tokens", False):
        extra_opts["max_output_tokens"] = 1100
    if product and effective_num_ctx is not None and getattr(provider, "supports_num_ctx", False):
        extra_opts["num_ctx"] = effective_num_ctx
    if product and request_timeout is not None and getattr(provider, "supports_per_call_timeout", False):
        extra_opts["timeout"] = request_timeout
    if product and keep_alive is not None and getattr(provider, "supports_keep_alive", False):
        extra_opts["keep_alive"] = keep_alive

    grounded = getattr(provider, "generate_grounded", None)
    result = (
        await grounded(system=system, user=user, evidence_ids=[c.chunk_id for c in evidence], **extra_opts)
        if callable(grounded)
        else await provider.generate(system=system, user=user, **extra_opts)
    )
    metrics.add_usage(result.usage)
    obj = _extract_json(result.text)
    raw_citations = [str(x) for x in obj.get("citations") or []]
    raw_status = str(obj.get("status") or "PARTIAL").upper()
    raw_ans = str(obj.get("answer") or "")
    answer = raw_ans.strip() if product else raw_ans
    computed_numbers: list[str] = []

    _EMPTY_MISSING = {"", "none", "null", "n/a", "không có", "không", "không thiếu", "no missing information", "không có thông tin thiếu"}
    raw_missing = [str(x).strip() for x in obj.get("missing_information") or [] if str(x).strip().casefold() not in _EMPTY_MISSING]
    missing = [*budget_missing, *raw_missing]

    unanch_refusal = False
    if product:
        status, status_normalized = normalize_status(raw_status)
        if status_normalized:
            missing.append("noncanonical model status normalized")
        if obj.get("truncated") and status == "COMPLETE":
            status = "PARTIAL"
        answer, computed_set = apply_calc_with_values(answer)
        computed_numbers = sorted(computed_set)
        if (unanchored_entities or topic_unanchored) and status == "COMPLETE":
            ans_low = re.sub(r"[*_`]+", "", answer).casefold()
            if not any(p in ans_low for p in _REFUSAL_PHRASES):
                status = "NO_EVIDENCE"
                answer = (
                    f"Tài liệu hiện có không chứa thông tin hay quy định về {', '.join(unanchored_entities)}."
                    if unanchored_entities
                    else "Tài liệu hiện có không chứa thông tin về nội dung được hỏi."
                )
                unanch_refusal = True
                raw_citations = []
                computed_numbers = []
        if status == "PARTIAL" and _is_pure_refusal(answer):
            status = "NO_EVIDENCE"
            raw_citations = []

        if status == "NO_EVIDENCE":
            valid, invalid = [], []
        else:
            valid, invalid = resolve_citations(raw_citations, evidence, answer, allow_grounded_fallback=True)
        metrics.add_citations(valid, invalid)
        if invalid:
            if status != "NO_EVIDENCE":
                status = "PARTIAL"
            missing.append("invalid citation locator(s) removed")
        if status == "COMPLETE" and not valid:
            status = "PARTIAL"
            missing.append("worker answer has no valid citation")
        if is_placeholder_answer(answer):
            answer = ""
            if status == "COMPLETE":
                status = "PARTIAL"
            missing.append("worker returned an empty answer")

        fallback_msg = (
            answer
            if unanch_refusal
            else (
                "No relevant evidence was found for this task."
                if reply_language == "en"
                else "Chưa tìm thấy evidence phù hợp cho task này."
            )
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
            # B139.2F6 (FIX-04): Promote uncited authorized chunk ONLY on explicit clause locator + domain substance overlap
            _CLAUSE_LOC_RE = re.compile(r"\b(?:Điều|Clause|Article)\s+\d+(?:\.\d+)?\b", re.I)
            _SUB_STOP = frozenset({
                "điều", "khoản", "theo", "hợp", "đồng", "quy", "định", "phần", "trên", "dưới",
                "trong", "ngoài", "hoặc", "nhưng", "được", "không", "chưa", "phải", "nếu", "khi",
                "bên", "của", "cho", "với", "từ", "đến", "tại", "và", "các", "những", "này",
                "clause", "article", "section", "under", "with", "from", "that", "this", "must", "shall",
            })
            def _substance_tokens(txt: str) -> set[str]:
                return {w for w in re.findall(r"[^\W\d_]{4,}", (txt or "").casefold()) if w not in _SUB_STOP}

            ans_clauses = {m.group(0).casefold() for m in _CLAUSE_LOC_RE.finditer(answer)}
            ans_substance = _substance_tokens(answer)
            for ch in evidence:
                if ch.chunk_id in valid:
                    continue
                ch_clauses = {m.group(0).casefold() for m in _CLAUSE_LOC_RE.finditer(ch.text or "")}
                matched_clauses = ans_clauses & ch_clauses
                if not matched_clauses:
                    continue
                ch_substance = _substance_tokens(f"{ch.text or ''} {getattr(ch, 'source_name', '') or ''}")
                shared_substance = ans_substance & ch_substance
                has_subclause = any("." in c for c in matched_clauses)
                if (has_subclause and len(shared_substance) >= 2) or len(shared_substance) >= 3:
                    valid.append(ch.chunk_id)

            status, answer, _, _ = check_product_evidence_claims(
                status,
                answer,
                evidence_text,
                user_request or task.goal,
                missing,
                evidence_chunks=evidence,
                ignored_identifiers=set(computed_numbers),
            )
    else:
        valid, invalid = validate_citations(raw_citations, evidence)
        metrics.add_citations(valid, invalid)
        status = raw_status
        if invalid:
            status = "PARTIAL"
            missing.append("invalid citation locator(s) removed")
        if status == "COMPLETE" and not valid:
            status = "PARTIAL"
            missing.append("worker answer has no valid citation")
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
        computed_numbers=computed_numbers,
    )
