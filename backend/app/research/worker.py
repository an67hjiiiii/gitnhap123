from __future__ import annotations
from app.core.citations import resolve_citations, validate_citations
from app.core.structured_output import is_placeholder_answer, parse_answer_json
from app.core.types import Task, TaskResult, SourceChunk, RunMetrics
from app.research.registry import profile
from app.core.answer_checks import IMG_MARK, apply_calc_with_values, detect_unanchored_entities, is_task_topic_unanchored
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
                       extra_hint: str | None = None) -> TaskResult:
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
    unanchored_entities: list[str] = []
    topic_unanchored = False
    if product:
        if user_request:
            user = f"[USER_REQUEST]{user_request[:2500]}[/USER_REQUEST]\n" + user
        user += "\n\n" + PRODUCT_WORKER_HINT
        unanchored_entities = detect_unanchored_entities(task.goal, evidence_text)
        topic_unanchored = is_task_topic_unanchored(task.goal, evidence_text)
        if unanchored_entities:
            user += (
                "\n\n[CẢNH BÁO ĐỐI CHIẾU TỪ KHÓA]: Các thực thể/văn bản sau có trong [TASK] nhưng XUẤT HIỆN 0 LẦN trong toàn bộ EVIDENCE: "
                + ", ".join(unanchored_entities)
                + ". TUYỆT ĐỐI KHÔNG gán giá dịch vụ/mức phạt của hạng mục khác thay cho các thực thể vắng mặt này; nếu [TASK] hỏi chính về chúng, PHẢI trả status=\"NO_EVIDENCE\" và citations=[]."
            )
        elif topic_unanchored:
            user += (
                "\n\n[CẢNH BÁO ĐỐI CHIẾU CHỦ ĐỀ]: Các từ khóa chủ đề chính trong [TASK] không xuất hiện trong bất kỳ đoạn EVIDENCE nào ở trên. "
                "Nếu EVIDENCE thực sự không đề cập đến nội dung này, BẮT BUỘC đặt status=\"NO_EVIDENCE\", citations=[], và nói rõ tài liệu không có thông tin; "
                "TUYỆT ĐỐI không tự tính ra con số mới hay lấy ngày ban hành / mức phí khác gán thay thế!"
            )
        if extra_hint:  # bước chọn nguồn tri thức: cho phép bổ sung kiến thức chung có nhãn
            user += "\n\n" + extra_hint
    elif reply_language in REPLY_LANGUAGE_HINT:
        user += "\n\n" + REPLY_LANGUAGE_HINT[reply_language]
    grounded = getattr(provider, "generate_grounded", None)
    limit = (
        {"max_output_tokens": 1100}
        if product and getattr(provider, "supports_per_call_output_tokens", False)
        else {}
    )
    result = (
        await grounded(system=system, user=user, evidence_ids=[c.chunk_id for c in evidence], **limit)
        if callable(grounded)
        else await provider.generate(system=system, user=user)
    )
    metrics.add_usage(result.usage)
    obj = _extract_json(result.text)
    raw_citations = [str(x) for x in obj.get("citations") or []]
    status = str(obj.get("status") or "PARTIAL").upper()
    answer = str(obj.get("answer") or "")
    computed_numbers: list[str] = []
    if product:
        answer, computed_set = apply_calc_with_values(answer)
        computed_numbers = sorted(computed_set)
        # Anti-Hallucination Grounding Guard: nếu thực thể định danh mạnh HOẶC toàn bộ chủ đề cốt lõi của [TASK]
        # xuất hiện 0 lần trong EVIDENCE nhưng mô hình lại trả lời khẳng định (status=COMPLETE, không có từ phủ định)
        # → chặn triệt để ảo giác đánh tráo điều khoản/bịa số liệu!
        if (unanchored_entities or topic_unanchored) and status == "COMPLETE":
            import re as _re
            ans_low = _re.sub(r"[*_`]+", "", answer).casefold()
            has_refusal = any(p in ans_low for p in _REFUSAL_PHRASES)
            if not has_refusal:
                status = "NO_EVIDENCE"
                if unanchored_entities:
                    answer = (
                        "Tài liệu hiện có không chứa thông tin hay quy định về "
                        + ", ".join(unanchored_entities)
                        + "."
                    )
                else:
                    answer = "Tài liệu hiện có không chứa thông tin về nội dung được hỏi."
                raw_citations = []
                computed_numbers = []
        # Chuẩn hóa tác tử từ chối thuần túy: nếu toàn bộ câu trả lời chỉ xác nhận tài liệu không có thông tin
        # nhưng mô hình nhỏ ghi nhầm status=PARTIAL và vẫn gắn citation rác → chuẩn hóa về NO_EVIDENCE, citations=[].
        if status == "PARTIAL" and _is_pure_refusal(answer):
            status = "NO_EVIDENCE"
            raw_citations = []
    if status == "NO_EVIDENCE":
        # Tác tử xác nhận không tìm thấy bằng chứng trong tài liệu: không đẩy đoạn đã đọc nhầm lên Nguồn tham chiếu!
        valid, invalid = [], []
    elif product:
        valid, invalid = resolve_citations(raw_citations, evidence, answer, allow_grounded_fallback=True)
    else:
        valid, invalid = validate_citations(raw_citations, evidence)
    metrics.add_citations(valid, invalid)
    _EMPTY_MISSING = {"", "none", "null", "n/a", "không có", "không", "không thiếu", "no missing information", "không có thông tin thiếu"}
    missing = [str(x).strip() for x in obj.get("missing_information") or [] if str(x).strip().casefold() not in _EMPTY_MISSING]
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
