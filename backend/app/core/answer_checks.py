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
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
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
    e = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", e)
    return e.replace(",", ".")


def fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{round(value):,}".replace(",", ".")
    s = f"{value:,.2f}".rstrip("0").rstrip(".")
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def apply_calc(text: str) -> str:
    """Thay mọi [[= biểu thức ]] bằng kết quả; biểu thức lỗi thì giữ nguyên chữ để người đọc thấy (không đoán)."""
    def sub(m: re.Match) -> str:
        try:
            v = _eval(ast.parse(_plain(m.group(1)), mode="eval"))
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            return m.group(1)
        return f"**{fmt(v)}**"
    return CALC.sub(sub, text)


_QUANTITY_UNIT = re.compile(r"(?<![\w.])(?P<n>\d+(?:[.,]\d+)?)\s*(?P<u>ng\u00e0y|days?|tu\u1ea7n|weeks?|th\u00e1ng|months?|n\u0103m|years?)(?!\w)", re.IGNORECASE)
_UNIT_ALIASES = {"ng\u00e0y":"day", "day":"day", "days":"day", "tu\u1ea7n":"week", "week":"week", "weeks":"week", "th\u00e1ng":"month", "month":"month", "months":"month", "n\u0103m":"year", "year":"year", "years":"year"}


def unsupported_quantities(answer: str, sources: str) -> list[tuple[str, str]]:
    """Detect unmatched number/time-unit pairs; not semantic entailment."""
    def quantities(text):
        return {(_norm(m.group('n')), _UNIT_ALIASES[m.group('u').casefold()]) for m in _QUANTITY_UNIT.finditer(text or '')}
    return sorted(quantities(answer) - quantities(sources))


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
    # "22%" trong nguồn cho phép câu trả lời viết 0.22 / 0,22 (cách viết tỷ lệ trong phép tính)
    for p in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", body):
        out.add(_norm(str(float(p.replace(",", ".")) / 100)))
    return out


def unsupported_numbers(answer: str, sources: str) -> list[str]:
    """Con số (>= 2 chữ số) trong câu trả lời mà không có nguyên văn trong nguồn (đoạn tài liệu + câu hỏi + chữ trong ảnh).
    Bỏ qua kết quả của máy tính và các toán hạng của phép tính."""
    calc_parts = " ".join(CALC.findall(answer))
    body = CALC.sub(" ", answer)
    body = re.sub(r"\([^()]*·\s*đoạn\s*\d+\)", " ", body)  # nhãn trích dẫn
    body = re.sub(r"src_[0-9a-f]+_c\d+", " ", body)
    known = numbers(sources) | numbers(calc_parts)
    out = [n for n in sorted(numbers(body)) if n not in known]
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


def finish(answer: str, sources: str) -> tuple[str, list[str]]:
    """Một bước cho câu trả lời sản phẩm: dọn, kiểm số, tính phép tính. Trả (câu trả lời, các số không có trong nguồn)."""
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
    return answer, bad


_CITATION_BRACKET = re.compile(r"\[[^\[\]\n]+\]")
_CLAIM_STOP = {"may", "can", "could", "should", "must", "will", "shall", "also", "that", "this", "the", "and", "are", "for", "with", "from", "c\u00e1c", "nh\u1eefng", "c\u1ee7a", "trong", "theo", "v\u00e0", "\u0111\u01b0\u1ee3c"}
_NEGATIVE = re.compile(r"\b(?:not|never|no|prohibit\w*|forbid\w*|den\w*|kh\u00f4ng|c\u1ea5m|ch\u01b0a)\b", re.I)
_POSITIVE = re.compile(r"\b(?:requir\w*|must|shall|b\u1eaft\s+bu\u1ed9c)\b", re.I)


def guard_cited_claims(answer: str, cited_texts: list[str] | dict[str, str]) -> tuple[str, bool, bool]:
    """Conservative lexical screen, not semantic entailment or per-sentence attribution."""
    from app.retrieval.text import terms

    def words(text):
        return terms(_CITATION_BRACKET.sub(' ', text)) - _CLAIM_STOP

    def supported(claim, evidence):
        claim_words = words(claim)
        if not claim_words:
            return False
        # Compare individual sentences, not unrelated negation in the chunk.
        sentences = re.split(r"(?<=[.!?])\s+|\n+", evidence)
        for sentence in sentences:
            evidence_words = words(sentence)
            overlap = len(claim_words & evidence_words)
            if overlap < min(2, len(claim_words)) or overlap / len(claim_words) < 0.6:
                continue
            if bool(_NEGATIVE.search(claim)) != bool(_NEGATIVE.search(sentence)):
                continue
            if _POSITIVE.search(claim) and _NEGATIVE.search(sentence):
                continue
            # A permission is not evidence of an obligation.
            if _POSITIVE.search(claim) and not _POSITIVE.search(sentence):
                continue
            if unsupported_numbers(claim, sentence) or unsupported_articles(claim, sentence) or unsupported_quantities(claim, sentence):
                continue
            # Preserve relative order when two named entities are present.
            names = re.findall(r"\b[A-Z][a-z]{2,}\b", claim)
            if len(names) >= 2:
                positions = [sentence.find(name) for name in names]
                if any(pos < 0 for pos in positions) or positions != sorted(positions):
                    continue
            return True
        return False

    fragments = re.split(r'(?<=[.!?])(?=\s+[^ \t\r\n\[])|(?<=\n)', answer or '')
    kept, removed, supported_count = [], False, 0
    for part in fragments:
        plain = _CITATION_BRACKET.sub('', part).strip()
        if not plain or re.match(r'^(?:ngu\u1ed3n|source)\s*:', plain, re.I):
            kept.append(part)
            continue
        if isinstance(cited_texts, dict):
            brackets = _CITATION_BRACKET.findall(part)
            inline = {cid for cid in cited_texts if any(re.search(r"(?<![\w])" + re.escape(cid) + r"(?![\w])", bracket) for bracket in brackets)}
            candidates = [cited_texts[cid] for cid in inline] if inline else list(cited_texts.values())
        else:
            candidates = cited_texts
        if any(supported(plain, evidence) for evidence in candidates):
            kept.append(part)
            supported_count += 1
        else:
            removed = True
    if not supported_count:
        return "Kh\u00f4ng \u0111\u1ee7 b\u1eb1ng ch\u1ee9ng \u0111\u1ec3 x\u00e1c nh\u1eadn n\u1ed9i dung tr\u1ea3 l\u1eddi.", True, False
    if removed:
        kept.append("\n\nKh\u00f4ng \u0111\u1ee7 b\u1eb1ng ch\u1ee9ng cho m\u1ed9t s\u1ed1 n\u1ed9i dung.")
    return ''.join(kept).strip(), removed, True


__all__ = ["IMG_MARK", "apply_calc", "clean", "finish", "fmt", "numbers", "unsupported_articles", "unsupported_numbers"]
