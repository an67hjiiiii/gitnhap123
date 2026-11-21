from __future__ import annotations
from app.core.answer_checks import IMG_MARK, finish
from app.core.citations import validate_citations
from app.core.structured_output import is_placeholder_answer, parse_answer_json
from app.core.types import RunMetrics, SourceChunk, TaskResult
from app.research.progress import answer_streamer


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
        "chỉ dùng số, + - * / và ngoặc (150% viết 1.5); hệ thống sẽ tự thay bằng kết quả, không viết lại kết quả sau dấu ]]. "
        "Ghi căn cứ đúng số Điều, khoản như trong bằng chứng. Không viết mục \"Các chunk ID liên quan\", không nhắc mã nhiệm vụ (T1, T2). "
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
                         product: bool = False, max_output_tokens: int | None = None) -> TaskResult:
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
    hints = PRODUCT_ANSWER_HINT if product else REPLY_LANGUAGE_HINT
    if reply_language in hints:
        user += "\n\n" + hints[reply_language]
    if product and IMG_MARK in query:  # ảnh dán vào ô chat: dữ kiện của trường hợp, không phải nguồn
        user += ("\n\nTRƯỜNG HỢP TRONG ẢNH: phần sau dấu \"" + IMG_MARK + "\" là dữ kiện người dùng đưa ra. Đối chiếu từng dữ kiện với "
                 "ngưỡng, điều kiện, thời hạn trong bằng chứng, viết rõ phép so sánh (ví dụ 0,72 < 1,0 nên không đạt) rồi kết luận. "
                 "Nếu quy định áp dụng có trong bằng chứng thì status là COMPLETE dù dữ kiện chỉ có trong ảnh.")
    grounded = getattr(provider, "generate_grounded", None)
    # câu trả lời có bảng dài hơn 700 token mặc định: ô chat cho giới hạn riêng (chỉ provider hỗ trợ)
    limit = {"max_output_tokens": max_output_tokens} if product and max_output_tokens and getattr(provider, "supports_per_call_output_tokens", False) else {}
    result = (
        await grounded(system=system, user=user, evidence_ids=[c.chunk_id for c in evidence], **limit, **answer_streamer(provider))
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

    if product and answer:  # hậu kiểm: máy tính thay phép tính, cảnh báo số không có trong nguồn (không áp cho thực nghiệm)
        answer, bad = finish(answer, evidence_text + "\n" + query)
        if bad:
            missing.append("numbers not found verbatim in evidence: " + ", ".join(bad[:8]))
            if status == "COMPLETE":
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
    )
