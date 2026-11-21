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


__all__ = ["IMG_MARK", "apply_calc", "clean", "finish", "fmt", "numbers", "unsupported_articles", "unsupported_numbers"]
