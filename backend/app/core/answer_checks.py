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


BARE = re.compile(r"(=\s*)(\d[\d.,]*(?:\s*[*×/]{1,2}\s*\d[\d.,]*)+)(?!\s*[=*×/+\-\d])")
_EXPLICIT_EQ_CHECK = re.compile(
    r"(=\s*)([0-9(][0-9.,()\s]*(?:[*×/+]|//|\s-\s|\s\+\s)[0-9.,()\s*/+\-]*[0-9)%])\s*=\s*(\d[\d.,]*(?:,\d+)?)(?!\s*[=*×/+\-\d])"
)
_SIMPLE_SLASH_PAIR = re.compile(r"^\d{1,4}\s*/\s*\d{1,4}$")
_DATE_OR_CODE_HYPHEN = re.compile(r"^\d{1,4}(?:\s*-\s*\d{1,4}){1,2}$")
_UNIT_MATH_CONSTANTS = frozenset({"1", "10", "100", "1000"})
_CALC_ECHO = re.compile(r"\*\*(\d[\d.,]*)\*\*\s*=\s*(?:\*\*)?(\d[\d.,]*)(?:\*\*)?")
_SYMBOLIC_CALC = re.compile(r"\[\[\s*=\s*([^\]]*[A-Za-zÀ-ỹđĐ_][^\]]*)\]\]")


def _eval_expr_text(expr: str) -> float:
    return float(_eval(ast.parse(_plain(expr), mode="eval")))


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

    # Nếu mô hình viết cả phép tính và vế phải tự tính nhẩm ("= 260M * 0,95 + 50M = 310M"), tính lại vế phải bằng AST
    def explicit_eq(m: re.Match) -> str:
        expr = m.group(2).strip()
        if _SIMPLE_SLASH_PAIR.fullmatch(expr) or _DATE_OR_CODE_HYPHEN.fullmatch(expr):
            return m.group(0)
        try:
            v = _eval(ast.parse(_plain(expr), mode="eval"), computed)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            return m.group(0)
        _record_value(computed, v)
        return f"{m.group(1)}{expr} = **{fmt(v)}**"

    text = _EXPLICIT_EQ_CHECK.sub(explicit_eq, text)

    # Đợt 8 Văn phòng 3D: mô hình hay viết "Phạt = 0.005*10*120000000 đồng" mà quên [[= ]]: tính luôn phép tính
    # đứng ngay sau dấu "=" và có ít nhất một phép nhân/chia (không đoán khi không có dấu "=").
    def bare(m: re.Match) -> str:
        expr = m.group(2).strip()
        if _SIMPLE_SLASH_PAIR.fullmatch(expr) or _DATE_OR_CODE_HYPHEN.fullmatch(expr):
            return m.group(0)
        try:
            v = _eval(ast.parse(_plain(expr), mode="eval"), computed)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            return m.group(0)
        _record_value(computed, v)
        return f"{m.group(1)}{expr} = **{fmt(v)}**"

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
    # V9 + B138: chỉ quy đổi "22%" -> 0.22 và "giảm 5%" -> 0.95 cho NGUỒN (known), không sinh từ câu trả lời
    if include_percent_ratios:
        for p in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", body):
            val = float(p.replace(",", "."))
            out.add(_norm(str(round(val / 100, 6))))
            if 0 < val < 100:
                out.add(_norm(str(round((100.0 - val) / 100.0, 6))))
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


def unsupported_calc_operands(answer: str, sources: str) -> list[str]:
    """Kiểm tra toán hạng bên trong [[= ... ]] hoặc phép tính có thực sự bắt nguồn từ bằng chứng/đầu vào hợp lệ không."""
    known = numbers(sources, include_percent_ratios=True)
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


def unsupported_numbers(
    answer: str,
    sources: str,
    extra_known: set[str] | None = None,
    *,
    ignored_identifiers: set[str] | None = None,
) -> list[str]:
    """Con số (>= 2 chữ số) trong câu trả lời mà không có nguyên văn trong nguồn (đoạn tài liệu + câu hỏi + chữ trong ảnh).
    Bỏ qua kết quả của máy tính, các toán hạng của phép tính và kết quả toán học chính xác tính từ số trong nguồn."""
    calc_parts = " ".join(CALC.findall(answer or ""))
    body = CALC.sub(" ", answer or "")
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
    if ignored_identifiers:
        known |= {_norm(str(x)) for x in ignored_identifiers if x}
    # Kết quả cuối cùng và các giá trị trung gian từ cây AST của [[= ... ]] đều là số đã được máy tính xác thực
    for expr in CALC.findall(answer or ""):
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


_WARNING_LINE_RE = re.compile(
    r"^\s*>\s*\*\*(?P<kind>Cần kiểm tra lại|Lưu ý căn cứ|Lưu ý phạm vi pháp lý|Cảnh báo nhất quán(?:\s*\([^)]+\))?|Đã hiệu chỉnh[^*]*|Kiểm chứng tính toán[^*]*)\s*:?\*\*\s*(?P<body>.*)$",
    re.I,
)


def deduplicate_warnings(text: str) -> str:
    """Deduplicate identical warning blockquotes by normalized warning identity while preserving distinct warnings."""
    lines = (text or "").splitlines()
    out: list[str] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    has_tagged_consistency = any(
        re.match(r"^\s*>\s*\*\*Cảnh báo nhất quán\s*\([^)]+\)\s*:?\*\*", ln.strip(), re.I)
        for ln in lines
    )
    for ln in lines:
        m = _WARNING_LINE_RE.match(ln.strip())
        if m:
            kind = re.sub(r"\s+", " ", m.group("kind").strip().casefold())
            body = m.group("body").strip()
            if kind.startswith("cảnh báo nhất quán"):
                if has_tagged_consistency and "(" not in kind:
                    continue
                sig: tuple[str, tuple[str, ...]] = ("cảnh báo nhất quán", ("single",))
            elif kind == "cần kiểm tra lại":
                toks = tuple(sorted({_norm(t) for t in _NUM.findall(body)}))
                sig = (kind, toks)
            elif kind == "lưu ý căn cứ":
                toks = tuple(sorted(_ARTICLE.findall(body)))
                sig = (kind, toks)
            else:
                toks = (re.sub(r"\s+", " ", body.casefold()),)
                sig = (kind, toks)
            if sig in seen:
                continue
            seen.add(sig)
        out.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _strip_warning_blockquotes(text: str) -> str:
    return "\n".join(ln for ln in (text or "").splitlines() if not _WARNING_LINE_RE.match(ln.strip()))


def finish_detailed(
    answer: str,
    sources: str,
    extra_known: set[str] | None = None,
    *,
    ignored_identifiers: set[str] | None = None,
) -> tuple[str, list[str], list[str]]:
    """Hậu kiểm đầy đủ cho câu trả lời sản phẩm: trả (câu trả lời, số không có trong nguồn, số Điều không có trong nguồn)."""
    answer = deduplicate_warnings(clean(answer))
    body_only = _strip_warning_blockquotes(answer)
    bad = unsupported_numbers(body_only, sources, extra_known=extra_known, ignored_identifiers=ignored_identifiers)
    arts = unsupported_articles(body_only, sources)
    answer = apply_calc(answer)
    if arts:
        answer += ("\n\n> **Lưu ý căn cứ:** câu trả lời nhắc " + ", ".join(f"Điều {a}" for a in arts[:6]) +
                   " nhưng đoạn tài liệu đã dùng không chứa Điều đó; số Điều có thể bị ghi nhầm, hãy xem đoạn nguồn.")
    if bad:
        answer += ("\n\n> **Cần kiểm tra lại:** các con số " + ", ".join(bad[:8]) +
                   " không có nguyên văn trong đoạn tài liệu đã dùng. Hãy bấm vào nguồn để đối chiếu.")
    return deduplicate_warnings(answer), bad, arts


def finish_checked(
    answer: str,
    sources: str,
    *,
    ignored_identifiers: set[str] | None = None,
) -> tuple[str, list[str], list[str]]:
    """Hậu kiểm sản phẩm: trả (câu trả lời, các số không có trong nguồn, các Điều không có trong nguồn)."""
    return finish_detailed(answer, sources, ignored_identifiers=ignored_identifiers)


def finish(answer: str, sources: str, extra_known: set[str] | None = None) -> tuple[str, list[str]]:
    """Một bước cho câu trả lời sản phẩm: dọn, kiểm số, tính phép tính. Trả (câu trả lời, các số không có trong nguồn)."""
    cleaned, bad, _arts = finish_detailed(answer, sources, extra_known=extra_known)
    return cleaned, bad


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
    """Dọn citation và câu khẳng định thiếu bằng chứng khi status là NO_EVIDENCE."""
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
    r"(?<!không\s)(?<!chưa\s)\b(?:(?:này|đơn|hồ sơ|điều khoản)\s+có\s+|có\s+)?(?:thỏa mãn|đáp ứng|hợp lệ|đạt yêu cầu|đủ điều kiện|đúng quy định|đúng nội quy(?:\s+và\s+quy\s+định)?|đúng yêu cầu|không vi phạm|đã được phê duyệt|thuộc phạm vi được phê duyệt)\b",
    re.I,
)
_MD_EMPHASIS = re.compile(r"\*{1,2}|_{1,2}")
_MD_EMPHASIS_SPAN = re.compile(r"(\*{1,2}|_{1,2})([^*\n_]+)\1")
_RULE_NEGATIVE = re.compile(
    r"\b(?:không\s+(?:thỏa mãn|đáp ứng|hợp lệ|đạt|đủ điều kiện|đúng quy định|đúng nội quy|đúng yêu cầu)|chưa\s+(?:đáp ứng|đạt|có|bàn giao|đủ điều kiện|được phê duyệt)|vi phạm|vượt\s+(?:quá|giới hạn)|trễ hạn)\b",
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
        if _PREMISE_TRAP_BEFORE.search(before) or _PREMISE_TRAP_AFTER.search(after):
            continue
        qtys.append(m.group(0))
    if qtys:
        base = base + "\n" + " ".join(qtys)
    return base


def _law_in_corpus(law: str, evidence_text: str, evidence_chunks: list | None = None) -> bool:
    """Xác minh văn bản luật thực sự có mặt trong bằng chứng theo danh tính tài liệu (source_name/heading), không tính nhắc tên trong tài liệu khác."""
    law_cf = law.casefold()
    if evidence_chunks:
        for ch in evidence_chunks:
            prov = getattr(ch, "provenance", None) or {}
            doc_type = str(prov.get("doc_type") or "").strip().lower()
            if doc_type == "contract":
                continue
            sname = str(getattr(ch, "source_name", "") or "").casefold()
            if law_cf in sname:
                return True
        return False
    return bool(re.search(
        rf"(?im)(?:^#+\s*.*{re.escape(law)}|^{re.escape(law)}\b[^\n]*(?:số\s*:?\s*\d+|QH\d+|NĐ-CP|TT-|20\d{{2}}))",
        evidence_text or "",
    ))


_CITED_STATUTE_ART_RE = re.compile(
    r"(?:Điều\s+(\d{1,3})\s+(Luật Thương mại|Bộ luật Dân sự|Bộ luật Hình sự|Bộ luật Lao động|Nghị định\s+\d+/\d+|Thông tư\s+\d+/\d+)"
    r"|(Luật Thương mại|Bộ luật Dân sự|Bộ luật Hình sự|Bộ luật Lao động|Nghị định\s+\d+/\d+|Thông tư\s+\d+/\d+)[^\n.;]{0,30}?\(?\s*Điều\s+(\d{1,3})\s*\)?)",
    re.I,
)
_POLICY_DESC_RE = re.compile(
    r"(?:theo\s+(?:chính\s+sách|quy\s+định\s+(?:chung|công\s+ty))[^\n]{0,30}(?:khi|nếu|phải)|hợp\s+lệ\s+khi|is\s+compliant\s+when)",
    re.I,
)


def _verify_legal_references(
    answer: str,
    evidence_chunks: list | None,
) -> tuple[list[str], list[str]]:
    """Verify `(statute, article)` references require both matching document identity and article number in the SAME authorized source."""
    if not evidence_chunks:
        return [], []
    unverified_laws: list[str] = []
    unverified_arts: list[str] = []
    for m in _CITED_STATUTE_ART_RE.finditer(answer or ""):
        art = m.group(1) or m.group(4)
        law = m.group(2) or m.group(3)
        if not art or not law:
            continue
        law_cf = law.casefold()
        art_pat = re.compile(rf"\bĐiều\s+{re.escape(art)}\b", re.I)
        matched = any(
            str((getattr(ch, "provenance", None) or {}).get("doc_type") or "").strip().lower() != "contract"
            and law_cf in str(getattr(ch, "source_name", "") or "").casefold()
            and art_pat.search(str(getattr(ch, "text", "") or ""))
            for ch in evidence_chunks
        )
        if not matched:
            if law not in unverified_laws:
                unverified_laws.append(law)
            if art not in unverified_arts:
                unverified_arts.append(art)
    return unverified_laws, unverified_arts


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
        if _ITEMIZED_LINE.match(ln) or ln.lstrip().startswith(">") or ln.lstrip().startswith("#") or _POLICY_DESC_RE.search(ln):
            new_lines.append(ln)
            continue
        sents = re.split(r"(?<=[.!?])\s+", ln) if ln.strip() else [ln]
        fixed_sents: list[str] = []
        for s in sents:
            if not s.strip() or s.strip().endswith("?"):
                fixed_sents.append(s)
                continue
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
    if "> **Cảnh báo nhất quán" not in out:
        out = banner + "\n\n" + out
    return out, True


_STATUTE_NUM_HEADER_RE = re.compile(
    r"\b(?:Nghị\s+định|Thông\s+tư|Luật|Bộ\s+luật|Quyết\s+định|Decree|Act|Law)\b[^\n]*",
    re.I,
)
_UNVERIFIED_LEGAL_VERDICT_RE = re.compile(
    r"(?:(?:có\s+thể\s+)?(?:vi\s+phạm|không\s+vi\s+phạm|vượt\s+quá\s+(?:giới\s+hạn|mức\s+trần|mức\s+tối\s+đa)|"
    r"trái\s+(?:với\s+)?(?:quy\s+định|pháp\s+luật)|không\s+phù\s+hợp\s+với|hợp\s+lệ\s+theo|đáp\s+ứng\s+theo|"
    r"exceeds?\s+(?:the\s+)?(?:statutory\s+)?(?:limit|cap)|violates?|complies?\s+with))",
    re.I,
)
_LEGAL_TAIL_START_RE = re.compile(
    r"(?:,?\s*(?:có\s+thể\s+)?(?:vượt\s+quá\s+(?:giới\s+hạn|mức\s+trần|mức\s+tối\s+đa)|"
    r"vi\s+phạm\s+(?:Luật|Bộ\s+luật|Nghị\s+định|Thông\s+tư|quy\s+định|pháp\s+luật)|"
    r"không\s+vi\s+phạm|trái\s+với\s+quy\s+định|theo\s+(?:Luật|Bộ\s+luật|Nghị\s+định|Thông\s+tư)))",
    re.I,
)


def _rewrite_unverified_legal_line(
    ln: str,
    missing_laws: list[str],
    missing_law_pat: re.Pattern[str],
) -> tuple[str, bool]:
    """Rewrite unverified statutory violation/limit/applicability assertions cleanly without mangling contract facts."""
    law_list = ", ".join(dict.fromkeys(missing_laws))
    if "|" in ln and not re.match(r"^\s*\|[-:\s|]+\|\s*$", ln):
        has_missing_mention = bool(
            missing_law_pat.search(ln)
            or _LEGAL_COMPLIANCE_CLAIM.search(ln)
            or _UNVERIFIED_LEGAL_VERDICT_RE.search(ln)
        )
        if not has_missing_mention:
            return ln, False
        cells = ln.split("|")
        if len(cells) >= 4:
            for idx in range(1, len(cells) - 1):
                if missing_law_pat.search(cells[idx]) and re.search(r"\b(?:Điều\s+\d+|mức\s+phạt|tối\s+đa|giới\s+hạn)\b", cells[idx], re.I):
                    cells[idx] = f" {law_list} (chưa được nạp) "
            cells[-2] = f" Chưa đủ căn cứ ({law_list} chưa được nạp) "
            return "|".join(cells), True
        return ln, False

    sents = re.split(r"(?<=[.!?])\s+(?!\d)", ln)
    out_sents: list[str] = []
    changed = False
    for sent in sents:
        s_trim = sent.strip()
        if not s_trim or s_trim.endswith("?") or "chưa đủ căn cứ kết luận" in s_trim:
            out_sents.append(sent)
            continue

        if re.search(r"\s+(?:và|nhưng)\s+", sent, re.I) and _LEGAL_COMPLIANCE_CLAIM.search(sent):
            parts = re.split(r"(\s+(?:và|nhưng)\s+)", sent, flags=re.I)
            new_parts: list[str] = []
            local_hit = False
            for part in parts:
                if re.fullmatch(r"\s+(?:và|nhưng)\s+", part, re.I):
                    new_parts.append(part)
                    continue
                if (_LEGAL_COMPLIANCE_CLAIM.search(part) or missing_law_pat.search(part)) and (
                    missing_law_pat.search(part) or not re.search(r"Điều\s+\d+", part, re.I)
                ):
                    cits_sub = _INLINE_SRC_CID.findall(part)
                    local_hit = True
                    part_laws = [lw for lw in dict.fromkeys(missing_laws) if re.search(re.escape(lw), part, re.I)]
                    law_str = ", ".join(part_laws) if part_laws else law_list
                    m_tail = _LEGAL_TAIL_START_RE.search(part)
                    prefix = part[: m_tail.start()].strip(" ,:-;") if m_tail else ""
                    if prefix and not re.match(r"^(?:Điều\s+khoản\s+này|Theo\s+)", prefix, re.I) and len(prefix) >= 8:
                        rep = f"{prefix}: chưa đủ căn cứ kết luận có vi phạm hay không ({law_str} chưa được nạp)"
                    else:
                        rep = f"chưa đủ căn cứ kết luận có vi phạm hay không ({law_str} chưa được nạp)"
                    if cits_sub:
                        rep += " " + " ".join(f"[{c}]" for c in cits_sub)
                    new_parts.append(rep)
                else:
                    new_parts.append(part)
            if local_hit:
                changed = True
                joined = "".join(new_parts).strip()
                if s_trim.endswith(".") and not joined.endswith("."):
                    joined += "."
                out_sents.append(joined)
                continue

        has_missing_or_legal_claim = bool(
            _LEGAL_COMPLIANCE_CLAIM.search(sent)
            or (missing_law_pat.search(sent) and (_UNVERIFIED_LEGAL_VERDICT_RE.search(sent) or _CITED_STATUTE_ART_RE.search(sent)))
        )
        if not has_missing_or_legal_claim:
            out_sents.append(sent)
            continue

        changed = True
        cits = _INLINE_SRC_CID.findall(sent)
        cite_str = (" " + " ".join(f"[{c}]" for c in cits)) if cits else ""
        sent_laws = [lw for lw in dict.fromkeys(missing_laws) if re.search(re.escape(lw), sent, re.I)]
        sent_law_str = ", ".join(sent_laws) if sent_laws else law_list

        lead_bullet = ""
        body_s = sent
        m_b = re.match(r"^(\s*(?:[-*•]|\d+[.)])\s+)", body_s)
        if m_b:
            lead_bullet = m_b.group(1)
            body_s = body_s[m_b.end():]
        body_no_cit = _INLINE_SRC_CID.sub("", body_s).strip().rstrip(".")

        m_tail = _LEGAL_TAIL_START_RE.search(body_no_cit)
        fact_prefix = body_no_cit[: m_tail.start()].strip(" ,:-;") if m_tail else ""
        fact_tails: list[str] = []
        if m_tail:
            after_tail = body_no_cit[m_tail.start():]
            for seg in re.split(r"\b(?:và|cũng như|đồng thời)\b", after_tail, flags=re.I):
                seg_clean = seg.strip(" ,.;:")
                if (
                    seg_clean
                    and not missing_law_pat.search(seg_clean)
                    and not _UNVERIFIED_LEGAL_VERDICT_RE.search(seg_clean)
                    and not _LEGAL_COMPLIANCE_CLAIM.search(seg_clean)
                    and not _CITED_STATUTE_ART_RE.search(seg_clean)
                    and re.search(r"(?:\d|bồi\s+thường|mức\s+phạt|bất\s+lợi|rủi\s+ro|hợp\s+đồng)", seg_clean, re.I)
                ):
                    fact_tails.append(seg_clean)

        is_generic_subject = bool(re.match(r"^(?:Điều\s+khoản\s+này|Hợp\s+đồng\s+này|Theo\s+[^,]+)$", fact_prefix, re.I))
        if fact_prefix and not is_generic_subject and not _LEGAL_COMPLIANCE_CLAIM.search(fact_prefix):
            rebuilt = f"{lead_bullet}{fact_prefix}"
            if fact_tails:
                rebuilt += f" ({'; '.join(fact_tails)})"
            rebuilt += f": chưa đủ căn cứ kết luận có vi phạm hay không ({sent_law_str} chưa được nạp){cite_str}."
        else:
            m_fact_mid = re.search(
                r"(?:mức\s+phạt\s+[^.,;]+?(?=\s+(?:vượt\s+quá|theo\s+|trái|$)))",
                body_no_cit,
                re.I,
            )
            extracted_facts: list[str] = []
            if m_fact_mid:
                extracted_facts.append(m_fact_mid.group(1).strip())
            for ft in fact_tails:
                if ft not in extracted_facts:
                    extracted_facts.append(ft)
            if extracted_facts:
                rebuilt = (
                    f"{lead_bullet}Hợp đồng nêu {', '.join(extracted_facts)}; "
                    f"tuy nhiên chưa đủ căn cứ kết luận có vi phạm hay không ({sent_law_str} chưa được nạp){cite_str}."
                )
            else:
                rebuilt = f"{lead_bullet}Chưa đủ căn cứ kết luận có vi phạm hay không ({sent_law_str} chưa được nạp){cite_str}."
        out_sents.append(rebuilt)

    return " ".join(out_sents), changed


def _strip_leading_query_echo(answer: str, query: str) -> str:
    """Remove a verbatim echoed user question paragraph at the top when followed by answer content."""
    ans = (answer or "").lstrip()
    q_head = (query or "").split(IMG_MARK, 1)[0].strip()
    if not ans or not q_head:
        return answer
    first_para, sep, rest = ans.partition("\n\n")
    if sep and rest.strip() and first_para.strip().casefold() == q_head.casefold():
        return rest.lstrip()
    first_line, sep_l, rest_l = ans.partition("\n")
    if sep_l and rest_l.strip() and first_line.strip().casefold() == q_head.casefold():
        return rest_l.lstrip()
    return answer


def check_product_evidence_claims(
    status: str,
    answer: str,
    evidence_text: str,
    query: str,
    missing: list[str],
    *,
    evidence_chunks: list | None = None,
    ignored_identifiers: set[str] | None = None,
) -> tuple[str, str, list[str], list[str]]:
    """Hậu kiểm sản phẩm chung cho vanilla và worker: đối chiếu số/Điều với bằng chứng, sửa kết luận mâu thuẫn và kiểm tra phạm vi luật ngoài kho."""
    answer = _strip_leading_query_echo(answer, query)
    sources_text = evidence_with_case_image_only(evidence_text, query)
    doc_title_nums: set[str] = set(ignored_identifiers or ())
    if evidence_chunks:
        for ch in evidence_chunks:
            sname = str(getattr(ch, "source_name", "") or "")
            if _STATUTE_NUM_HEADER_RE.search(sname):
                doc_title_nums |= numbers(sname)
    calc_bad_ops = unsupported_calc_operands(answer, sources_text)
    answer, bad, bad_arts = finish_checked(answer, sources_text, ignored_identifiers=doc_title_nums)
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

    answer, contradicted = _reconcile_rule_conclusions(answer, missing)
    if contradicted and status == "COMPLETE":
        status = "PARTIAL"

    asked_laws = _EXTERNAL_STATUTE.findall(query or "")
    missing_laws = [law for law in asked_laws if not _law_in_corpus(law, evidence_text, evidence_chunks)]
    unverified_ref_laws, unverified_ref_arts = _verify_legal_references(answer, evidence_chunks)
    for ulaw in unverified_ref_laws:
        if ulaw not in missing_laws:
            missing_laws.append(ulaw)
    for uart in unverified_ref_arts:
        if uart not in bad_arts:
            bad_arts.append(uart)

    if missing_laws:
        law_list = ", ".join(dict.fromkeys(missing_laws))
        missing_law_pat = re.compile(
            r"(?:"
            + "|".join(re.escape(lw) for lw in dict.fromkeys(missing_laws))
            + r")(?:\s+\d{4})?(?:\s*\([^)]*\))?",
            re.I,
        )
        rewritten_lines: list[str] = []
        scope_changed = False
        for ln in answer.splitlines():
            s_strip = ln.strip()
            if (
                not s_strip
                or s_strip.endswith("?")
                or s_strip.startswith(("#", ">"))
                or "chưa đủ căn cứ kết luận" in s_strip
            ):
                rewritten_lines.append(ln)
                continue
            new_ln, line_changed = _rewrite_unverified_legal_line(ln, missing_laws, missing_law_pat)
            if line_changed:
                scope_changed = True
            rewritten_lines.append(new_ln)
        if scope_changed or unverified_ref_laws:
            answer = "\n".join(rewritten_lines)
            missing.append("out-of-corpus external law claim unverified: " + law_list[:80])
            if status == "COMPLETE":
                status = "PARTIAL"
            note = ("\n\n> **Lưu ý phạm vi pháp lý:** Văn bản luật bên ngoài ("
                    + law_list
                    + ") chưa được nạp trong tài liệu đang xét; đây chỉ là phân tích rủi ro nội dung hiện có, không phải kết luận đối chiếu pháp luật đầy đủ.")
            if note.strip() not in answer:
                answer = answer + note

    if status == "COMPLETE" and _PARTIAL_GAP_ADMISSION.search(answer):
        missing.append("partial missing evidence admitted in multi-part response")
        status = "PARTIAL"

    return status, deduplicate_warnings(answer), bad, bad_arts


__all__ = [
    "IMG_MARK",
    "apply_calc",
    "apply_calc_with_values",
    "check_product_evidence_claims",
    "clean",
    "deduplicate_warnings",
    "detect_unanchored_entities",
    "evidence_with_case_image_only",
    "finish",
    "finish_checked",
    "finish_detailed",
    "fmt",
    "guard_no_evidence",
    "is_task_topic_unanchored",
    "normalize_status",
    "numbers",
    "sanitize_evidence_text",
    "strip_invalid_inline_citations",
    "unsupported_articles",
    "unsupported_calc_operands",
    "unsupported_numbers",
]
