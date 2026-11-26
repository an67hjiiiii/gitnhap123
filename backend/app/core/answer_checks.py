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
# số kiểu Việt (12.000.000 / 1,5 / 150%) và số nghìn nhiều dấu phẩy kiểu Anh (1,080,000); bỏ số thứ tự đầu dòng ("1.", "2)")
_NUM = re.compile(
    r"(?<![\w.,])\d{1,3}(?:\.\d{3})+(?:,\d+)?|"
    r"(?<![\w.,])\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?|"
    r"(?<![\w.,])\d+(?:[.,]\d+)?"
)
IMG_MARK = "[Ảnh đính kèm, chữ nhận dạng được]:"


def _eval(node, intermediates: set[str] | None = None):
    if isinstance(node, ast.Expression):
        return _eval(node.body, intermediates)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        val = _OPS[type(node.op)](_eval(node.left, intermediates), _eval(node.right, intermediates))
        if intermediates is not None and isinstance(val, (int, float)) and abs(val) <= 1e15:
            _record_value(intermediates, val)
        return val
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        val = _OPS[type(node.op)](_eval(node.operand, intermediates))
        if intermediates is not None and isinstance(val, (int, float)) and abs(val) <= 1e15:
            _record_value(intermediates, val)
        return val
    raise ValueError("biểu thức không hợp lệ")


def _plain(expr: str) -> str:
    """'12.000.000 × 1,5' → '12000000*1.5', '0,5%' → '(0.5/100)' (an toàn thứ tự ưu tiên với mọi toán tử)."""
    e = expr.replace("×", "*").replace("x", "*").replace("÷", "/")
    # dấu chấm nghìn (12.000.000); "0.005" là số thập phân kiểu Anh, giữ nguyên
    e = re.sub(r"(?<![\d.])\d{1,3}(?:\.\d{3})+(?![\d.])", lambda m: m.group(0) if m.group(0).startswith("0.") else m.group(0).replace(".", ""), e)
    # số nghìn nhiều dấu phẩy kiểu Anh (1,080,000)
    e = re.sub(r"(?<![\d,])\d{1,3}(?:,\d{3}){2,}(?![\d,])", lambda m: m.group(0).replace(",", ""), e)
    e = e.replace(",", ".")
    e = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", e)
    return e.replace("%", "/100")


def fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{round(value):,}".replace(",", ".")
    s = f"{value:,.2f}".rstrip("0").rstrip(".")
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


BARE = re.compile(r"(=\s*)(\d[\d.,]*(?:\s*[*×/]{1,2}\s*\d[\d.,]*)+)(?!\s*[=*×/\d])")
_CALC_ECHO = re.compile(r"\*\*(\d[\d.,]*)\*\*\s*=\s*(?:\*\*)?(\d[\d.,]*)(?:\*\*)?")
_SYMBOLIC_CALC = re.compile(r"\[\[\s*=\s*([^\]]*[A-Za-zÀ-ỹđĐ_][^\]]*)\]\]")


def _dedup_calc_echo(text: str) -> str:
    """V9: gộp lặp số dạng '**450.000** = 450.000 VNĐ' → '**450.000** VNĐ' khi 2 vế cùng giá trị."""
    def _rep(m: re.Match) -> str:
        if _norm(m.group(1)) == _norm(m.group(2)):
            return f"**{m.group(1)}**"
        return m.group(0)
    return _CALC_ECHO.sub(_rep, text)


def _record_value(bucket: set[str], v: float) -> None:
    bucket.add(_norm(fmt(v)))
    bucket.add(_norm(str(round(v, 2))))
    if abs(v - round(v)) < 1e-6:
        bucket.add(_norm(str(int(round(v)))))


def apply_calc_with_values(text: str) -> tuple[str, set[str]]:
    """Thay mọi [[= biểu thức ]] bằng kết quả và trả kèm tập giá trị đã được máy tính xác thực."""
    computed: set[str] = set()

    def sub(m: re.Match) -> str:
        try:
            v = _eval(ast.parse(_plain(m.group(1)), mode="eval"), computed)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            return m.group(1)
        _record_value(computed, v)
        return f"**{fmt(v)}**"

    text = CALC.sub(sub, text)
    text = _dedup_calc_echo(text)

    # Đợt 8 Văn phòng 3D: mô hình hay viết "Phạt = 0.005*10*120000000 đồng" mà quên [[= ]]: tính luôn phép tính
    # đứng ngay sau dấu "=" và có ít nhất một phép nhân/chia (không đoán khi không có dấu "=").
    def bare(m: re.Match) -> str:
        try:
            v = _eval(ast.parse(_plain(m.group(2)), mode="eval"), computed)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            return m.group(0)
        _record_value(computed, v)
        return f"{m.group(1)}{m.group(2).strip()} = **{fmt(v)}**"

    return BARE.sub(bare, text), computed


def apply_calc(text: str) -> str:
    """Thay mọi [[= biểu thức ]] bằng kết quả; biểu thức lỗi thì giữ nguyên chữ để người đọc thấy (không đoán)."""
    return apply_calc_with_values(text)[0]


def _norm(token: str) -> str:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", token):
        t = token.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?", token):
        t = token.replace(",", "")
    else:
        t = token
    t = t.replace(",", ".")
    try:
        f = float(t)
    except ValueError:
        return t
    return str(int(f)) if f == int(f) else str(f)


def numbers(text: str, *, include_percent_ratios: bool = False) -> set[str]:
    body = re.sub(r"(?m)^\s*\d+[.)]\s+", " ", text or "")  # số thứ tự đầu dòng
    out = {_norm(n) for n in _NUM.findall(body)}
    # V9: chỉ quy đổi "22%" -> 0.22 cho NGUỒN (known), tuyệt đối không sinh 0.054000000000000006 từ câu trả lời!
    if include_percent_ratios:
        for p in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", body):
            out.add(_norm(str(round(float(p.replace(",", ".")) / 100, 6))))
    return out


_INLINE_EXPR = re.compile(
    r"(?:\(\s*)?\d[\d.,]*%?(?:\s*(?:[+\-×÷]|//|[*/])\s*(?:\(\s*)?\d[\d.,]*%?(?:\s*\))?)+(?:\s*\))?"
)
# V9: rút gọn đơn vị tiếng Việt ngắn xen giữa số và toán tử để kiểm chứng phép tính tự nhiên
# (vd. "5 lần vi phạm - 2 lần miễn trừ tối đa = 3 lần", "3 lần × 150.000 VNĐ = 450.000 VNĐ", "1.260 triệu + 1.140 triệu = 2.400").
_UNIT_BEFORE_OP = re.compile(
    r"(\d[\d.,]*%?)\s+(?:[A-Za-zÀ-ỹđĐ]{1,14}(?:\s+[A-Za-zÀ-ỹđĐ]{1,14}){0,3})\s*(?=(?:[+\-×÷=]|//|[*/]))"
)
_TY_SCALE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:tỷ|tỉ)\b", re.IGNORECASE)
_TRIEU_SCALE = re.compile(r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?:triệu|tr)\b", re.IGNORECASE)


def _scale_equivalents(sources: str) -> set[str]:
    """V9: cho phép quy đổi tương đương đơn vị tỷ ↔ triệu có trong nguồn (vd. '24.000 triệu' ↔ '24 tỷ', '8,4 tỷ' ↔ '8.400 triệu')."""
    extra: set[str] = set()
    for raw in _TY_SCALE.findall(sources or ""):
        try:
            val = float(_norm(raw))
        except ValueError:
            continue
        extra.add(_norm(str(round(val * 1000, 2))))
    for raw in _TRIEU_SCALE.findall(sources or ""):
        try:
            val = float(_norm(raw))
        except ValueError:
            continue
        if val >= 100:
            extra.add(_norm(str(round(val / 1000, 2))))
    return extra


_ADD_PROSE = re.compile(r"\b(cộng thêm|cộng với|tổng cộng|tổng là|tổng số|tổng ngày|tổng tiền)\b", re.IGNORECASE)
_SUB_PROSE = re.compile(r"\b(trừ đi|bị trừ|còn lại|chênh lệch|tiết kiệm|vượt quá|vượt ngưỡng|giảm còn|giảm xuống|dư)\b", re.IGNORECASE)
_MUL_PROSE = re.compile(r"\b(nhân với|mỗi lần|mỗi ngày|mỗi tháng|gấp)\b", re.IGNORECASE)
_PCT_PROSE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_PCT_ACTION = re.compile(r"\b(cắt giảm|giảm|tăng|dồn|chiếm|bằng|tương đương|phân bổ|còn|xuống|từ)\b", re.IGNORECASE)


def _prose_sentence_results(answer: str, allowed: set[str]) -> set[str]:
    """V9: công nhận kết quả cộng/trừ/nhân/tỷ lệ % viết bằng lời tiếng Việt trong cùng một đoạn văn
    (vd. '12 ngày ... cộng thêm 2 ngày, tổng cộng 14 ngày'; 'cắt giảm 50% từ 350 triệu xuống 175 triệu')
    khi CẢ HAI toán hạng đều thuộc allowed."""
    derived: set[str] = set()
    prev_nums: list[float] = []
    for para in re.split(r"\n+", answer or ""):
        if not para.strip():
            continue
        nums_in_para = []
        for raw in _NUM.findall(para):
            n = _norm(raw)
            if n in allowed:
                try:
                    nums_in_para.append(float(n))
                except ValueError:
                    pass
        nums_in_para = nums_in_para[:10]
        has_add = bool(_ADD_PROSE.search(para))
        has_sub = bool(_SUB_PROSE.search(para))
        has_mul = bool(_MUL_PROSE.search(para))
        pct_vals = []
        if _PCT_ACTION.search(para):
            for raw_p in _PCT_PROSE.findall(para):
                np = _norm(raw_p)
                if np in allowed:
                    try:
                        pct_vals.append(float(np))
                    except ValueError:
                        pass
        if not (has_add or has_sub or has_mul or pct_vals):
            if nums_in_para:
                prev_nums = nums_in_para
            continue
        cands: list[float] = []
        for i in range(len(nums_in_para)):
            for j in range(i + 1, len(nums_in_para)):
                a, b = nums_in_para[i], nums_in_para[j]
                if has_add:
                    cands.append(a + b)
                if has_sub:
                    cands.append(abs(a - b))
                if has_mul and abs(a * b) <= 1e15:
                    cands.append(a * b)
        pct_bases = list(dict.fromkeys(nums_in_para + prev_nums))[:12]
        for p in pct_vals[:4]:
            ratio = p / 100.0
            for a in pct_bases:
                if a == p:
                    continue
                cands.extend((a * ratio, a * (1.0 - ratio), a * (1.0 + ratio)))
        if nums_in_para:
            prev_nums = nums_in_para
        for val in cands:
            if abs(val) > 1e15:
                continue
            for c in (
                _norm(str(round(val, 2))),
                _norm(str(int(round(val)))) if abs(val - round(val)) < 1e-6 else "",
                _norm(fmt(val)),
            ):
                if c and c not in allowed:
                    derived.add(c)
    return derived


def _verified_arithmetic_results(answer: str, known: set[str]) -> set[str]:
    """Nhận diện kết quả số học hợp lệ khi câu trả lời nêu rõ phép tính (kể cả có đơn vị tiếng Việt xen giữa,
    vd. '3 lần × 150.000 VNĐ = 450.000 VNĐ', '12 ngày + 2 ngày = 14 ngày', hoặc diễn giải bằng lời tiếng Việt)
    với mọi toán hạng đều có căn cứ."""
    allowed = set(known)
    derived: set[str] = set()
    normalized_answer = _UNIT_BEFORE_OP.sub(r"\1 ", answer or "")
    scan_texts = (answer or "", normalized_answer)
    # Chạy 3 vòng để hỗ trợ phép tính nối tiếp nhiều bước (vd. 5 - 2 = 3 -> 3 × 150.000 = 450.000; 8 / 4 = 2 -> 12 cộng thêm 2 = 14)
    for _ in range(3):
        added_any = False
        for text_view in scan_texts:
            for m in _INLINE_EXPR.finditer(text_view):
                raw_expr = m.group(0).strip()
                # V9: cân bằng ngoặc mở/đóng lẻ khi biểu thức nằm trong ngoặc dạng "(8 / 4 = 2)" -> "8 / 4"
                while raw_expr.startswith("(") and raw_expr.count("(") > raw_expr.count(")"):
                    raw_expr = raw_expr[1:].strip()
                while raw_expr.endswith(")") and raw_expr.count(")") > raw_expr.count("("):
                    raw_expr = raw_expr[:-1].strip()
                # Bỏ qua dạng ngày tháng/tỷ số kiểu 31/03 hoặc 2025/2026
                if re.fullmatch(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", raw_expr):
                    continue
                operands = {_norm(n) for n in _NUM.findall(raw_expr)}
                if len(operands) < 2 and "+" not in raw_expr and "*" not in raw_expr and "×" not in raw_expr:
                    continue
                if not operands or not all(op in allowed for op in operands):
                    continue
                try:
                    val = _eval(ast.parse(_plain(raw_expr), mode="eval"))
                except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
                    continue
                if not isinstance(val, (int, float)) or abs(val) > 1e15:
                    continue
                for candidate in (
                    _norm(str(round(val, 2))),
                    _norm(str(round(val, 1))),
                    _norm(str(int(round(val)))) if abs(val - round(val)) < 1e-6 else "",
                    _norm(fmt(val)),
                ):
                    if candidate and candidate not in allowed:
                        allowed.add(candidate)
                        derived.add(candidate)
                        added_any = True
        prose_new = _prose_sentence_results(answer or "", allowed)
        if prose_new:
            allowed.update(prose_new)
            derived.update(prose_new)
            added_any = True
        if not added_any:
            break
    return derived


_LAW_CODE_YEAR = re.compile(r"\b\d+/(?:19|20)\d{2}/[A-ZĐ0-9-]+\b", re.IGNORECASE)
_REFUSAL_SENT_RE = re.compile(
    r"không\s+(?:có|quy\s+định|đề\s+cập|được\s+cung\s+cấp|được\s+đề\s+cập|tìm\s+thấy|nêu)",
    re.IGNORECASE,
)


def unsupported_numbers(answer: str, sources: str, extra_known: set[str] | None = None) -> list[str]:
    """Con số (>= 2 chữ số) trong câu trả lời mà không có nguyên văn trong nguồn (đoạn tài liệu + câu hỏi + chữ trong ảnh).
    Bỏ qua kết quả của máy tính, các toán hạng của phép tính và kết quả toán học chính xác tính từ số trong nguồn."""
    calc_parts = " ".join(CALC.findall(answer))
    body = CALC.sub(" ", answer)
    body = re.sub(r"\([^()]*·\s*đoạn\s*\d+\)", " ", body)  # nhãn trích dẫn
    body = re.sub(r"src_[0-9a-f]+_c\d+", " ", body)
    # Bỏ mã hiệu văn bản kiểu '13/2023/NĐ-CP' khi xuất hiện trong câu từ chối ('không có trong hợp đồng')
    body = "\n".join(
        _LAW_CODE_YEAR.sub(" ", line) if _REFUSAL_SENT_RE.search(line) else line
        for line in body.splitlines()
    )
    known = numbers(sources, include_percent_ratios=True) | _scale_equivalents(sources) | numbers(calc_parts)
    if extra_known:
        known |= {_norm(x) for x in extra_known if x}
    # Kết quả cuối cùng và các giá trị trung gian từ cây AST của [[= ... ]] đều là số đã được máy tính xác thực
    for expr in CALC.findall(answer):
        try:
            v = _eval(ast.parse(_plain(expr), mode="eval"), known)
            _record_value(known, v)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            pass
    known = known | _verified_arithmetic_results(body, known)
    out = [n for n in sorted(numbers(body)) if len(n.replace(".", "")) >= 2 and n not in known]
    return out


_JUNK = [re.compile(p, re.I | re.M) for p in (
    # Chỉ xóa mục "Các chunk ID liên quan:" cùng danh sách mã đoạn ngay dưới nó (không xóa nhầm nội dung/bảng phía sau)
    r"^\s*(?:\*\*)?(?:các\s+)?chunk\s*id(?:\s+liên quan)?(?:\*\*)?\s*:?\s*(?:\n\s*(?:[-*•]\s*)?(?:`?\[?src_[0-9a-f]+_c\d+\]?`?[,;\s]*)+)*\s*$",
    r"\bT\d+\b(?=\s+(?:chỉ ra|cho thấy|nêu))",
    r"\s*\((?:xem\s+)?(?:task\s+)?T\d+(?:\s*(?:,|và|&)\s*(?:task\s+)?T\d+)*\)",
    r"^\s*Đối với\s+\[TASK\]\s*['\"]?[^\n'\"]+['\"]?\s*:\s*",
)]


def clean(text: str) -> str:
    for p in _JUNK:
        text = p.sub("", text)
    text = re.sub(r"\|\s*Chunk ID\s*\|", "| Nguồn |", text)
    # V9: dọn cú pháp mẫu có biến chữ bị rò ra câu trả lời (vd. "[[= (X - N) * mức ]]" -> "(X - N) × mức")
    text = _SYMBOLIC_CALC.sub(lambda m: m.group(1).strip().replace("*", "×"), text)
    return text.strip()


_ARTICLE = re.compile(r"\bĐiều\s+(\d{1,3})\b")
_SECTION_NUM = re.compile(
    r"(?m)^\s*(?:\[src_[0-9a-f]+_c\d+\]\s*)?(?:#{1,4}\s+)?(\d{1,2})\.\s+\S|\bMục\s+(\d{1,2})\b"
)

# Thực thể / mã định danh mạnh dùng cho kiểm tra chống đánh tráo đối tượng (Anti-Hallucination Grounding Gate)
_STRONG_LAW_REF = re.compile(
    r"\b(Nghị\s+định|Thông\s+tư|Quyết\s+định|Nghị\s+quyết|Phụ\s+lục|"
    r"Decree|Circular|Decision|Resolution|Appendix)\s+(?:No\.?\s*)?(\d+(?:/\d+)?(?:-[A-ZĐ]+)?)\b",
    re.IGNORECASE,
)
_LAW_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "nghị định": ("nghị định", "decree"),
    "decree": ("nghị định", "decree"),
    "thông tư": ("thông tư", "circular"),
    "circular": ("thông tư", "circular"),
    "quyết định": ("quyết định", "decision"),
    "decision": ("quyết định", "decision"),
    "nghị quyết": ("nghị quyết", "resolution"),
    "resolution": ("nghị quyết", "resolution"),
    "phụ lục": ("phụ lục", "appendix"),
    "appendix": ("phụ lục", "appendix"),
}
_STRONG_ACRO_OR_MODEL = re.compile(
    r"\b(?:[A-Z]{3,6}(?:\s+\d+(?:[.,]\d+)?(?:\s+[A-Z][a-z]+)?)?)\b"
)
_GENERIC_ACRONYMS = {
    "VNĐ", "VND", "USD", "EUR", "VAT", "KPI", "SLA", "API", "RAG", "LLM", "PDF", "CSV", "DOCX", "XLSX",
    "CNTT", "BHYT", "BHXH", "BHTN", "TNHH", "CTCP", "UBND", "TP", "HN", "HCM", "QĐ", "NĐ", "TT",
    "CEO", "CFO", "CTO", "COO", "HR", "IT", "AI", "ROI", "ROAS", "CPA", "CTR", "GPA", "NDA", "VIAC",
    "IELTS", "TOEIC", "ISO", "SQL", "GPU", "CPU", "RAM", "TLS", "AES", "SSO", "MFA", "RBAC", "GDPR",
    "USER", "REQUEST", "TASK", "EVIDENCE", "JSON", "HTML", "HTTP", "HTTPS", "URL", "URI",
}


def detect_unanchored_entities(query_text: str, evidence_text: str) -> list[str]:
    """Phát hiện các thực thể định danh mạnh (văn bản pháp quy song ngữ kiểu 'Nghị định 13' / 'Decree 13',
    mã/thiết bị/thương hiệu kiểu 'MRI', 'HSBC') có trong câu hỏi nhưng xuất hiện 0 lần trong toàn bộ `evidence_text`."""
    if not query_text or not evidence_text:
        return []
    ev_low = evidence_text.casefold()
    found: list[str] = []
    seen: set[str] = set()

    for m in _STRONG_LAW_REF.finditer(query_text):
        kind = re.sub(r"\s+", " ", m.group(1)).strip().casefold()
        num = m.group(2).strip()
        variants = _LAW_EQUIVALENTS.get(kind, (kind,))
        present = any(
            re.search(rf"\b{re.escape(v)}\s+(?:no\.?\s*)?{re.escape(num.casefold())}\b", ev_low)
            for v in variants
        )
        canonical = f"{variants[0].capitalize()} {num}"
        key = canonical.casefold()
        if not present and key not in seen:
            seen.add(key)
            found.append(canonical)

    for m in _STRONG_ACRO_OR_MODEL.finditer(query_text):
        term = re.sub(r"\s+", " ", m.group(0)).strip()
        head = term.split()[0]
        if head in _GENERIC_ACRONYMS or len(head) < 3:
            continue
        # Bỏ qua từ tiếng Việt toàn chữ hoa (nếu có dấu tiếng Việt như ĐIỀU, MỤC)
        if any(ord(ch) > 127 for ch in head):
            continue
        key = head.casefold()
        if key not in seen and not re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", ev_low):
            seen.add(key)
            found.append(term)
    return found


_TOPIC_STOP_FOLD = {
    "va", "la", "cua", "cho", "trong", "voi", "mot", "cac", "nhung", "duoc", "khong", "co",
    "theo", "tu", "den", "tai", "lieu", "thong", "tin", "quy", "dinh", "chinh", "sach", "hien",
    "nay", "nam", "thang", "ngay", "muc", "bao", "nhieu", "phan", "tren", "duoi", "sau", "truoc",
    "khi", "thi", "neu", "gi", "nao", "bao", "gom", "phi", "gia", "tien", "chi", "tiet", "moi",
    "hang", "sinh", "vien", "nhan", "cong", "ty", "hop", "dong", "dich", "vu", "bieu", "bang",
    "so", "luong", "ty", "le", "thoi", "han", "gian", "lich", "ke", "hoach", "chuong", "trinh",
    "du", "kien", "cu", "the", "toi", "da", "thieu", "biet", "dua", "vao", "hay", "hoac", "ve",
    "cung", "cap", "ap", "dung", "tinh", "ra", "sao", "nhu", "the", "de", "bo", "sung", "them",
    "nghia", "vu", "ben", "chu", "yeu", "tong", "cong", "cac", "loai", "nhom", "doi", "tuong",
    "2024", "2025", "2026", "2027",
}


def _fold_topic(text: str) -> str:
    import unicodedata
    s = (text or "").replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()


def is_task_topic_unanchored(task_goal: str, evidence_text: str) -> bool:
    """Trả True khi chủ đề tiếng Việt cốt lõi của `task_goal` (đặc biệt sau nhãn 'Nghĩa vụ:') hoàn toàn vắng mặt
    trong `evidence_text` (0 cụm 2 từ nội dung đặc thù khớp và <25% từ đơn đặc thù khớp).
    Dùng để chặn ảo giác bịa số liệu/ngày tháng (vd. hỏi 'ký túc xá / kỳ hè' trên tài liệu không có)."""
    if not task_goal or not evidence_text:
        return False
    # Ưu tiên phần tiếng Việt gốc sau 'Nghĩa vụ:' nếu planner đã gắn vào task.goal
    m = re.search(r"Nghĩa\s+vụ\s*:\s*(.+)$", task_goal, re.IGNORECASE)
    segment = m.group(1).strip() if m else task_goal
    # Chỉ áp dụng khi segment là câu tiếng Việt (có ít nhất 2 ký tự có dấu tiếng Việt)
    if sum(1 for ch in segment if ord(ch) > 127) < 2:
        return False
    words = [w for w in re.findall(r"[a-z0-9]{2,}", _fold_topic(segment)) if w not in _TOPIC_STOP_FOLD and not w.isdigit()]
    if len(words) < 3:
        return False
    bigrams = list(dict.fromkeys(f"{a} {b}" for a, b in zip(words, words[1:])))
    if len(bigrams) < 2:
        return False
    ev_fold = _fold_topic(evidence_text)
    ev_words = set(re.findall(r"[a-z0-9]{2,}", ev_fold))
    bi_hits = sum(1 for bg in bigrams if bg in ev_fold)
    if bi_hits > 0:
        return False
    uniq_words = list(dict.fromkeys(words))
    word_hits = sum(1 for w in uniq_words if w in ev_words)
    return (word_hits / len(uniq_words)) < 0.25


def unsupported_articles(answer: str, sources: str) -> list[str]:
    """Số Điều câu trả lời viện dẫn mà các đoạn đã dùng không có (21/11: "theo Điều 3 khoản 5" trong khi đúng là Điều 14).
    Nếu văn bản nguồn không đánh số bằng chữ 'Điều' mà dùng tiêu đề mục số ('# 1.', '2.', 'Mục 3'), chấp nhận số mục tương ứng."""
    known = set(_ARTICLE.findall(sources))
    if not known:
        for m in _SECTION_NUM.finditer(sources or ""):
            num = m.group(1) or m.group(2)
            if num:
                known.add(num)
    return sorted({n for n in _ARTICLE.findall(answer) if n not in known}, key=int)


_INJECTION_LINE = re.compile(
    r"(?im)^.*(?:ignore\s+(?:all\s+)?previous\s+instructions?|disregard\s+(?:all\s+)?(?:previous|prior)|"
    r"system\s+override|output\s+only\s+|bỏ\s+qua\s+mọi\s+hướng\s+dẫn\s+trước).*$"
)


def sanitize_evidence_text(text: str) -> str:
    """OBS-B101-01: trung hòa dòng mang dạng chỉ thị prompt injection trong tài liệu nguồn trước khi đưa vào LLM."""
    if not text:
        return ""
    return _INJECTION_LINE.sub("[đoạn văn bản bị loại trừ do chứa chỉ thị điều khiển]", text)


def finish_detailed(answer: str, sources: str, extra_known: set[str] | None = None) -> tuple[str, list[str], list[str]]:
    """Hậu kiểm đầy đủ cho câu trả lời sản phẩm: trả (câu trả lời, số không có trong nguồn, số Điều không có trong nguồn)."""
    answer = clean(answer)
    bad = unsupported_numbers(answer, sources, extra_known=extra_known)
    arts = unsupported_articles(answer, sources)
    answer = apply_calc(answer)
    if arts:
        answer += ("\n\n> **Lưu ý căn cứ:** câu trả lời nhắc " + ", ".join(f"Điều {a}" for a in arts[:6]) +
                   " nhưng đoạn tài liệu đã dùng không chứa Điều đó; số Điều có thể bị ghi nhầm, hãy xem đoạn nguồn.")
    if bad:
        answer += ("\n\n> **Cần kiểm tra lại:** các con số " + ", ".join(bad[:8]) +
                   " không có nguyên văn trong đoạn tài liệu đã dùng. Hãy bấm vào nguồn để đối chiếu.")
    return answer, bad, arts


def finish(answer: str, sources: str, extra_known: set[str] | None = None) -> tuple[str, list[str]]:
    """Một bước cho câu trả lời sản phẩm: dọn, kiểm số, tính phép tính. Trả (câu trả lời, các số không có trong nguồn)."""
    cleaned, bad, _arts = finish_detailed(answer, sources, extra_known=extra_known)
    return cleaned, bad


__all__ = [
    "IMG_MARK",
    "apply_calc",
    "apply_calc_with_values",
    "clean",
    "detect_unanchored_entities",
    "finish",
    "finish_detailed",
    "fmt",
    "is_task_topic_unanchored",
    "numbers",
    "sanitize_evidence_text",
    "unsupported_articles",
    "unsupported_numbers",
]
