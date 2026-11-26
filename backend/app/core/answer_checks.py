"""Hậu kiểm câu trả lời ô chat sản phẩm (21/11): tính phép tính bằng mã, cảnh báo con số không có trong nguồn, dọn rác trình bày.

Chỉ dùng ở product_mode; thực nghiệm A/B/C không đi qua đây. Không gọi mô hình.
"""
from __future__ import annotations

import ast
import operator
import re

# Mô hình viết phép tính dạng [[= 12000000/26/8*4*1.5 ]]; máy tính thay bằng kết quả (mô hình 4B hay nhân sai).
# mô hình đôi khi quên dấu "=" đầu hoặc tự ghi kết quả sau: [[3.000 * 1,5 = 45]] → chỉ lấy vế trái, máy tính lại
CALC = re.compile(r"\[\[\s*=?\s*([0-9(][^\]=]{0,200}?[0-9)%])\s*(?:=[^\]]*)?\]\]")
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
# số kiểu Việt: 12.000.000 / 1,5 / 150% ; bỏ số thứ tự đầu dòng ("1.", "2)")
_NUM = re.compile(r"(?<![\w.,])\d{1,3}(?:\.\d{3})+(?:,\d+)?|(?<![\w.,])\d+(?:[.,]\d+)?")
IMG_MARK = "[Ảnh đính kèm, chữ nhận dạng được]:"


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("biểu thức không hợp lệ")


def _plain(expr: str) -> str:
    """'12.000.000 × 1,5' → '12000000*1.5' (dấu chấm nghìn, dấu phẩy thập phân, × ÷)."""
    e = expr.replace("×", "*").replace("x", "*").replace("÷", "/").replace("%", "/100")
    # dấu chấm nghìn (12.000.000); "0.005" là số thập phân kiểu Anh, giữ nguyên
    e = re.sub(r"(?<![\d.])\d{1,3}(?:\.\d{3})+(?![\d.])", lambda m: m.group(0) if m.group(0).startswith("0.") else m.group(0).replace(".", ""), e)
    return e.replace(",", ".")


def fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{round(value):,}".replace(",", ".")
    s = f"{value:,.2f}".rstrip("0").rstrip(".")
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


BARE = re.compile(r"(=\s*)(\d[\d.,]*(?:\s*[*×/]{1,2}\s*\d[\d.,]*)+)(?!\s*[=*×/+\-\d])")
_EXPLICIT_EQ_CHECK = re.compile(
    r"(=\s*)([0-9(][0-9.,()\s]*(?:[*×/+]|//|\s-\s|\s\+\s)[0-9.,()\s*/+\-]*[0-9)%])\s*=\s*(\d[\d.,]*(?:,\d+)?)(?!\s*[=*×/+\-\d])"
)
_SIMPLE_SLASH_PAIR = re.compile(r"^\d{1,4}\s*/\s*\d{1,4}$")
_DATE_OR_CODE_HYPHEN = re.compile(r"^\d{1,4}(?:\s*-\s*\d{1,4}){1,2}$")
_UNIT_MATH_CONSTANTS = frozenset({"1", "10", "100", "1000"})


def _eval_expr_text(expr: str) -> float:
    return float(_eval(ast.parse(_plain(expr), mode="eval")))


def apply_calc(text: str) -> str:
    """Thay mọi [[= biểu thức ]] bằng kết quả; biểu thức lỗi thì giữ nguyên chữ để người đọc thấy (không đoán)."""
    def sub(m: re.Match) -> str:
        try:
            v = _eval_expr_text(m.group(1))
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            return m.group(1)
        return f"**{fmt(v)}**"
    text = CALC.sub(sub, text)

    # Nếu mô hình viết cả phép tính và vế phải tự tính nhẩm ("= 260M * 0.95 + 50M = 310M"), tính lại vế phải bằng AST
    def explicit_eq(m: re.Match) -> str:
        expr = m.group(2).strip()
        if _SIMPLE_SLASH_PAIR.fullmatch(expr) or _DATE_OR_CODE_HYPHEN.fullmatch(expr):
            return m.group(0)
        try:
            v = _eval_expr_text(expr)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            return m.group(0)
        return f"{m.group(1)}{expr} = **{fmt(v)}**"
    text = _EXPLICIT_EQ_CHECK.sub(explicit_eq, text)

    # Đợt 8 Văn phòng 3D: mô hình hay viết "Phạt = 0.005*10*120000000 đồng" mà quên [[= ]]: tính luôn phép tính
    # đứng ngay sau dấu "=" và có ít nhất một phép nhân/chia (không đoán khi có +/- đơn lẻ như "10/2 + 3" hay ngày 15/12).
    def bare(m: re.Match) -> str:
        expr = m.group(2).strip()
        if _SIMPLE_SLASH_PAIR.fullmatch(expr):
            return m.group(0)
        try:
            v = _eval_expr_text(expr)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            return m.group(0)
        return f"{m.group(1)}{expr} = **{fmt(v)}**"
    return BARE.sub(bare, text)


def _norm(token: str) -> str:
    t = token.replace(".", "") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", token) else token
    t = t.replace(",", ".")
    try:
        f = float(t)
    except ValueError:
        return t
    return str(int(f)) if f == int(f) else str(f)


def numbers(text: str) -> set[str]:
    body = re.sub(r"(?m)^\s*\d+[.)]\s+", " ", text or "")  # số thứ tự đầu dòng
    out = {_norm(n) for n in _NUM.findall(body)}
    # "22%" trong nguồn cho phép câu trả lời viết 0.22 / 0,22 và hệ số bù chiết khấu 0.95 cho "giảm 5%"
    for p in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", body):
        val = float(p.replace(",", "."))
        out.add(_norm(str(round(val / 100, 6))))
        if 0 < val < 100:
            out.add(_norm(str(round((100.0 - val) / 100.0, 6))))
    return out


def unsupported_calc_operands(answer: str, sources: str) -> list[str]:
    """Kiểm tra toán hạng bên trong [[= ... ]] hoặc phép tính có thực sự bắt nguồn từ bằng chứng/đầu vào hợp lệ không."""
    known = numbers(sources)
    bad_operands: list[str] = []
    exprs = list(CALC.findall(answer or ""))
    exprs.extend(m.group(2).strip() for m in _EXPLICIT_EQ_CHECK.finditer(answer or ""))
    for expr in exprs:
        try:
            _eval_expr_text(expr)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            continue
        for raw_num in _NUM.findall(expr):
            normed = _norm(raw_num)
            if (len(normed.replace(".", "")) >= 2 or "." in normed) and normed not in known and normed not in _UNIT_MATH_CONSTANTS:
                if normed not in bad_operands:
                    bad_operands.append(normed)
    return sorted(bad_operands)


def unsupported_numbers(answer: str, sources: str) -> list[str]:
    """Con số (>= 2 chữ số) trong câu trả lời mà không có nguyên văn trong nguồn (đoạn tài liệu + câu hỏi + chữ trong ảnh).
    Bỏ qua kết quả của máy tính và các toán hạng của phép tính."""
    calc_parts = " ".join(CALC.findall(answer or ""))
    body = CALC.sub(" ", answer or "")
    body = re.sub(r"\([^()]*·\s*đoạn\s*\d+\)", " ", body)  # nhãn trích dẫn
    body = re.sub(r"src_[0-9a-f]+_c\d+", " ", body)
    known = numbers(sources) | numbers(calc_parts)
    out = [n for n in sorted(numbers(body)) if len(n.replace(".", "")) >= 2 and n not in known]
    return out


_JUNK = [re.compile(p, re.I | re.M) for p in (
    r"^\s*(?:\*\*)?(?:các\s+)?chunk\s*id(?:\s+liên quan)?(?:\*\*)?\s*:?\s*$[\s\S]*\Z",  # mục "Các chunk ID liên quan:" ở cuối
    r"\bT\d+\b(?=\s+(?:chỉ ra|cho thấy|nêu))",
)]


def clean(text: str) -> str:
    for p in _JUNK:
        text = p.sub("", text)
    text = re.sub(r"\|\s*Chunk ID\s*\|", "| Nguồn |", text)
    return text.strip()


_ARTICLE = re.compile(r"\bĐiều\s+(\d{1,3})\b")


def unsupported_articles(answer: str, sources: str) -> list[str]:
    """Số Điều câu trả lời viện dẫn mà các đoạn đã dùng không có (21/11: "theo Điều 3 khoản 5" trong khi đúng là Điều 14)."""
    known = set(_ARTICLE.findall(sources))
    return sorted({n for n in _ARTICLE.findall(answer) if n not in known}, key=int)


def finish_checked(answer: str, sources: str) -> tuple[str, list[str], list[str]]:
    """Hậu kiểm sản phẩm: trả (câu trả lời, các số không có trong nguồn, các Điều không có trong nguồn)."""
    answer = clean(answer)
    bad = unsupported_numbers(answer, sources)
    arts = unsupported_articles(answer, sources)
    answer = apply_calc(answer)
    if arts:
        answer += ("\n\n> **Lưu ý căn cứ:** câu trả lời nhắc " + ", ".join(f"Điều {a}" for a in arts[:6]) +
                   " nhưng đoạn tài liệu đã dùng không chứa Điều đó; số Điều có thể bị ghi nhầm, hãy xem đoạn nguồn.")
    if bad:
        answer += ("\n\n> **Cần kiểm tra lại:** các con số " + ", ".join(bad[:8]) +
                   " không có nguyên văn trong đoạn tài liệu đã dùng. Hãy bấm vào nguồn để đối chiếu.")
    return answer, bad, arts


def finish(answer: str, sources: str) -> tuple[str, list[str]]:
    """Một bước cho câu trả lời sản phẩm: dọn, kiểm số, tính phép tính. Trả (câu trả lời, các số không có trong nguồn)."""
    out, bad, _ = finish_checked(answer, sources)
    return out, bad


_CANONICAL_STATUSES = frozenset({"COMPLETE", "PARTIAL", "NO_EVIDENCE"})
_INLINE_SRC_CID = re.compile(r"\[?(src_[0-9a-f]{16}_c\d{4})\]?", re.I)
_TRAILING_SOURCE_LINE = re.compile(r"\n+\s*(?:Nguồn|Sources?)\s*:.*$", re.I | re.S)
_TRIM_MISSING = frozenset({"top_evidence_trimmed_to_num_ctx", "trailing_evidence_trimmed_to_num_ctx"})


def strip_invalid_inline_citations(text: str, allowed_ids: set[str]) -> tuple[str, list[str]]:
    """Loại bỏ mọi mã src_<16hex>_cNNNN inline trong văn bản nếu không nằm trong allowed_ids."""
    invalid: list[str] = []

    def _sub(match: re.Match) -> str:
        cid = match.group(1)
        if cid in allowed_ids:
            return match.group(0)
        if cid not in invalid:
            invalid.append(cid)
        return ""

    cleaned = _INLINE_SRC_CID.sub(_sub, text or "")
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, invalid


def normalize_status(raw_status: str | None) -> tuple[str, bool]:
    """Chuẩn hóa trạng thái mô hình về COMPLETE/PARTIAL/NO_EVIDENCE; trạng thái lạ hạ về PARTIAL."""
    s = str(raw_status or "PARTIAL").strip().upper()
    if s in _CANONICAL_STATUSES:
        return s, False
    return "PARTIAL", True


def guard_no_evidence(
    status: str,
    answer: str,
    valid: list[str],
    missing: list[str],
    query: str,
    fallback: str,
    *,
    product: bool = False,
    reply_language: str | None = None,
) -> tuple[str, str, list[str]]:
    """Dọn citation và câu khẳng định thiếu bằng chứng khi status là NO_EVIDENCE.

    Ở chế độ sản phẩm (`product=True`), mọi văn bản tự do của mô hình khi status là NO_EVIDENCE
    đều được thay bằng thông báo từ chối an toàn do ứng dụng kiểm soát (không giữ tail text chưa kiểm chứng),
    chỉ nối thêm ghi chú hệ thống đã xác thực nếu ngữ cảnh bị cắt do giới hạn cửa sổ ngữ cảnh.
    """
    if status != "NO_EVIDENCE":
        return status, answer, valid
    if valid:
        valid = []
        missing.append("citations cleared because status is NO_EVIDENCE")
    upper_ans = answer.upper()
    q_norm = (query or "").strip().casefold()
    prompt_echo = (
        not answer
        or "USER REQUEST:" in upper_ans
        or "EVIDENCE:" in upper_ans
        or "[EVIDENCE]" in upper_ans
        or "[TASK]" in upper_ans
        or (q_norm and answer.strip().casefold() == q_norm)
    )
    if prompt_echo:
        answer = fallback
        missing.append("prompt echo stripped on NO_EVIDENCE")
    elif product:
        cleaned, stripped_inline = strip_invalid_inline_citations(_TRAILING_SOURCE_LINE.sub("", answer).strip(), set())
        if stripped_inline:
            missing.append("inline citations stripped on NO_EVIDENCE")
        if cleaned.strip() != fallback.strip():
            missing.append("ungrounded NO_EVIDENCE prose replaced with safe refusal")
        answer = fallback
    if product and any(m in _TRIM_MISSING for m in missing):
        trim_note = (
            " (System note: part of the document context was trimmed due to the context window limit.)"
            if reply_language == "en"
            else " (Lưu ý hệ thống: một phần đoạn tài liệu bị cắt bớt do giới hạn cửa sổ ngữ cảnh.)"
        )
        if trim_note.strip() not in answer:
            answer = f"{answer}{trim_note}"
    return status, answer, valid


_USER_INPUT_QTY = re.compile(
    r"(?<!Điều\s)(?<!điều\s)\b(?:\d{1,3}(?:[.,]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?:sinh viên|nhân viên|người|khách|ly|cái|chiếc|suất|bản|giờ|tiếng|ngày|tuần|tháng|năm|trang|lần|tín chỉ|học phần)\b",
    re.I,
)
_PREMISE_TRAP_BEFORE = re.compile(
    r"\b(?:mỗi nhân viên được|nhân viên được|người lao động được|được nghỉ|được hưởng|được thưởng|phải báo trước|tối đa)\s*$",
    re.I,
)
_PREMISE_TRAP_AFTER = re.compile(r"^\s*(?:đúng không|phải không|có phải|không\s*\?)", re.I)
_RULE_POSITIVE = re.compile(
    r"(?<!không\s)(?<!chưa\s)\b(?:(?:này|đơn|hồ sơ|điều khoản)?\s*có\s+)?(?:thỏa mãn|đáp ứng|hợp lệ|đạt yêu cầu|đủ điều kiện|đúng quy định|đúng nội quy(?:\s+và\s+quy\s+định)?)\b",
    re.I,
)
_MD_EMPHASIS = re.compile(r"\*{1,2}|_{1,2}")
_MD_EMPHASIS_SPAN = re.compile(r"(\*{1,2}|_{1,2})([^*\n_]+)\1")
_RULE_NEGATIVE = re.compile(
    r"\b(?:không\s+(?:thỏa mãn|đáp ứng|hợp lệ|đạt|đủ điều kiện|đúng quy định|đúng nội quy)|chưa\s+(?:đáp ứng|đạt|có|bàn giao|đủ điều kiện)|vi phạm|vượt\s+(?:quá|giới hạn)|trễ hạn)\b",
    re.I,
)
_OVERALL_NEGATIVE_SENTENCE = re.compile(
    r"\b(?:chưa\s+đủ\s+điều\s+kiện|không\s+(?:đạt|hợp lệ|đúng quy định|đúng nội quy|thỏa mãn)|vi phạm)\b",
    re.I,
)
_ITEMIZED_LINE = re.compile(r"^\s*(?:\||[-*•]\s+|\d+[.)]\s+)")
_EXTERNAL_STATUTE = re.compile(
    r"\b(?:Luật Thương mại|Bộ luật Dân sự|Bộ luật Hình sự|Bộ luật Lao động|Nghị định\s+\d+/\d+|Thông tư\s+\d+/\d+)\b",
    re.I,
)
_LEGAL_COMPLIANCE_CLAIM = re.compile(
    r"(?:\*{1,2}|_{1,2})?\b(?:không vi phạm(?:\*{1,2}|_{1,2})?(?:\s+(?:Luật\s+Thương\s+mại|Bộ\s+luật\s+Dân\s+sự|Luật\s+Lao\s+động|pháp\s+luật|luật|quy\s+định\s+pháp\s+luật)(?:\s*(?:/|hoặc|và)\s*(?:Bộ\s+luật\s+Dân\s+sự|Luật\s+Thương\s+mại))?)?|vi phạm luật|đúng pháp luật|trái pháp luật|hợp pháp|bất hợp pháp)\b(?:\*{1,2}|_{1,2})?",
    re.I,
)
_PARTIAL_GAP_ADMISSION = re.compile(
    r"\b(?:không được đề cập|không có thông tin|chưa có thông tin|không nêu)\b",
    re.I,
)


def evidence_with_case_image_only(evidence_text: str, query: str) -> str:
    """Chỉ giữ bằng chứng thật (kèm OCR ảnh nếu có và số lượng hợp lệ người dùng nhập; loại số tiền/Điều bẫy và tiền đề quy định chưa kiểm chứng)."""
    base = evidence_text or ""
    q = query or ""
    if IMG_MARK in q:
        typed_part, img_part = q.split(IMG_MARK, 1)
        base = base + "\n" + img_part
    else:
        typed_part = q
    qtys: list[str] = []
    for m in _USER_INPUT_QTY.finditer(typed_part):
        before = typed_part[max(0, m.start() - 48):m.start()]
        after = typed_part[m.end():min(len(typed_part), m.end() + 40)]
        # Tiền đề quy định/bẫy xác nhận ("mỗi nhân viên được nghỉ 30 ngày đúng không?") không phải dữ kiện đầu vào được duyệt
        if _PREMISE_TRAP_BEFORE.search(before) or _PREMISE_TRAP_AFTER.search(after):
            continue
        qtys.append(m.group(0))
    if qtys:
        base = base + "\n" + " ".join(qtys)
    return base


def _law_in_corpus(law: str, evidence_text: str, evidence_chunks: list | None = None) -> bool:
    """Xác minh văn bản luật thực sự có mặt trong bằng chứng thay vì chỉ bị nhắc tên trong điều khoản hợp đồng."""
    law_cf = law.casefold()
    if evidence_chunks:
        for ch in evidence_chunks:
            prov = getattr(ch, "provenance", None) or {}
            doc_type = str(prov.get("doc_type") or "").strip().lower()
            if doc_type == "contract":
                continue
            sname = str(getattr(ch, "source_name", "") or "").casefold()
            ctext = str(getattr(ch, "text", "") or "").casefold()
            if doc_type == "legal_doc" and (law_cf in sname or law_cf in ctext):
                return True
            if law_cf in sname:
                return True
        return False
    return bool(re.search(
        rf"(?im)(?:^#+\s*.*{re.escape(law)}|{re.escape(law)}.*(?:số\s*:?\s*\d+|QH\d+|NĐ-CP|TT-))",
        evidence_text or "",
    ))


def _reconcile_rule_conclusions(answer: str, missing: list[str]) -> tuple[str, bool]:
    """Loại bỏ/sửa câu kết luận khẳng định đạt mâu thuẫn với điều kiện NOT_MET; không báo nhầm với bảng/liệt kê đối chiếu hợp lệ."""
    plain_answer = _MD_EMPHASIS.sub("", answer)
    if not _RULE_NEGATIVE.search(plain_answer):
        return answer, False
    _repl = "chưa đủ điều kiện kết luận đạt do còn điều kiện chưa thỏa mãn"
    lines = answer.splitlines()
    changed = False
    new_lines: list[str] = []
    for ln in lines:
        if _ITEMIZED_LINE.match(ln) or ln.lstrip().startswith(">") or ln.lstrip().startswith("#"):
            new_lines.append(ln)
            continue
        # Chỉ xử lý câu kết luận tổng thể khẳng định đạt (kể cả bọc Markdown **...**/*...*/_..._) khi chưa bị phủ định
        sents = re.split(r"(?<=[.!?])\s+", ln) if ln.strip() else [ln]
        fixed_sents: list[str] = []
        for s in sents:
            plain_s = _MD_EMPHASIS.sub("", s)
            if _RULE_POSITIVE.search(plain_s) and not _OVERALL_NEGATIVE_SENTENCE.search(plain_s):
                def _sub_md_span(match: re.Match) -> str:
                    before = s[max(0, match.start() - 12):match.start()]
                    inner = match.group(2)
                    if re.search(r"(?:không|chưa)\s*$", before, re.I):
                        return match.group(0)
                    if _RULE_POSITIVE.search(inner):
                        return _repl
                    return match.group(0)

                s2 = _MD_EMPHASIS_SPAN.sub(_sub_md_span, s)
                s2 = _RULE_POSITIVE.sub(_repl, s2)
                if s2 != s:
                    changed = True
                    s = s2
            fixed_sents.append(s)
        new_lines.append(" ".join(fixed_sents) if len(fixed_sents) > 1 else fixed_sents[0])
    if not changed:
        return answer, False
    out = "\n".join(new_lines)
    missing.append("contradictory compliance conclusion vs unmet condition")
    banner = "> **Cảnh báo nhất quán:** Chưa kết luận đạt do có điều kiện chưa thỏa mãn hoặc vi phạm trong phần đối chiếu bên dưới."
    if banner not in out:
        out = banner + "\n\n" + out
    return out, True


def check_product_evidence_claims(
    status: str,
    answer: str,
    evidence_text: str,
    query: str,
    missing: list[str],
    *,
    evidence_chunks: list | None = None,
) -> tuple[str, str, list[str], list[str]]:
    """Hậu kiểm sản phẩm chung cho vanilla và worker: đối chiếu số/Điều với bằng chứng, sửa kết luận mâu thuẫn và kiểm tra phạm vi luật ngoài kho."""
    sources_text = evidence_with_case_image_only(evidence_text, query)
    calc_bad_ops = unsupported_calc_operands(answer, sources_text)
    answer, bad, bad_arts = finish_checked(answer, sources_text)
    extra_ops = [op for op in calc_bad_ops if op not in bad]
    if extra_ops:
        bad = sorted({*bad, *extra_ops})
        if "Cần kiểm tra lại:" not in answer:
            answer += ("\n\n> **Cần kiểm tra lại:** các con số " + ", ".join(extra_ops[:8]) +
                       " không có nguyên văn trong đoạn tài liệu đã dùng. Hãy bấm vào nguồn để đối chiếu.")
    if bad_arts:
        missing.append("articles not found verbatim in evidence: " + ", ".join(bad_arts[:6]))
        if status == "COMPLETE":
            status = "PARTIAL"
    if bad:
        missing.append("numbers not found verbatim in evidence: " + ", ".join(bad[:8]))
        if status == "COMPLETE":
            status = "PARTIAL"

    # FIX-05 (CHECK-B1/B2): sửa câu kết luận đạt mâu thuẫn với điều kiện NOT_MET; bảo toàn bảng/danh sách mixed-condition hợp lệ
    answer, contradicted = _reconcile_rule_conclusions(answer, missing)
    if contradicted and status == "COMPLETE":
        status = "PARTIAL"

    # FIX-05 (CHECK-E1): kết luận tuân thủ luật bên ngoài khi văn bản luật không có trong kho (kể cả khi hợp đồng chỉ nhắc tên luật)
    asked_laws = _EXTERNAL_STATUTE.findall(query or "")
    missing_laws = [law for law in asked_laws if not _law_in_corpus(law, evidence_text, evidence_chunks)]
    if missing_laws and _LEGAL_COMPLIANCE_CLAIM.search(answer):
        law_list = ", ".join(dict.fromkeys(missing_laws))
        missing.append("out-of-corpus external law claim unverified: " + law_list[:80])
        if status == "COMPLETE":
            status = "PARTIAL"
        answer = _LEGAL_COMPLIANCE_CLAIM.sub(
            f"chưa đủ căn cứ kết luận có vi phạm hay không ({law_list} chưa được nạp)",
            answer,
        )
        note = ("\n\n> **Lưu ý phạm vi pháp lý:** Văn bản luật bên ngoài ("
                + law_list
                + ") chưa được nạp trong tài liệu đang xét; đây chỉ là phân tích rủi ro nội dung hiện có, không phải kết luận đối chiếu pháp luật đầy đủ.")
        if note.strip() not in answer:
            answer = answer + note

    # Workstream E: khi mô hình tự thừa nhận có ý không được đề cập thì không tuyên bố COMPLETE
    if status == "COMPLETE" and _PARTIAL_GAP_ADMISSION.search(answer):
        missing.append("partial missing evidence admitted in multi-part response")
        status = "PARTIAL"

    return status, answer, bad, bad_arts


__all__ = [
    "IMG_MARK",
    "apply_calc",
    "check_product_evidence_claims",
    "clean",
    "evidence_with_case_image_only",
    "finish",
    "finish_checked",
    "fmt",
    "guard_no_evidence",
    "normalize_status",
    "numbers",
    "strip_invalid_inline_citations",
    "unsupported_articles",
    "unsupported_numbers",
]
