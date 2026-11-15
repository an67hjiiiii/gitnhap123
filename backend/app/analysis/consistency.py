"""Kiểm tra mâu thuẫn giữa các tài liệu của cùng một dự án.

Bước 1 (không dùng mô hình): tách câu có tính quy định (có con số hoặc từ như "phải", "tối đa") ở mỗi tài liệu,
ghép cặp câu ở hai tài liệu khác nhau cùng nói về một chủ đề nhưng khác con số hoặc khác phủ định.
Bước 2: tác tử xét từng cặp nghi vấn: mâu thuẫn, nhất quán hay không liên quan. Nhờ bước 1, số lần gọi mô hình
tỷ lệ với số cặp nghi vấn chứ không với bình phương số câu.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.analysis.design import _call, _obj, _text
from app.analysis.evaluation import _content_tokens
from app.analysis.traceability import _numbers
from app.core.types import SourceChunk
from app.research.registry import profile

_NORMATIVE = re.compile(r"\b(phải|không được|bắt buộc|tối đa|tối thiểu|chỉ|cấm|luôn|must|shall|never|only|at least|at most)\b", re.I)
_NEGATION = re.compile(r"\b(không|cấm|chưa|never|not|no)\b", re.I)
# Dòng thông tin tài liệu và tham chiếu mục/mã tài liệu không phải giá trị quy định để so sánh.
_METADATA = re.compile(r"^(mã tài liệu|phiên bản|version|ngày|date|người phê duyệt|đơn vị soạn thảo|áp dụng cho|dành cho|căn cứ|hệ quản trị|địa chỉ gốc)\b", re.I)
_REFERENCE = re.compile(r"\b(?:mục|section|phần)\s*\d+(?:\.\d+)*|\bPN-[A-Z]+-\d+\b|^\d+(?:\.\d+)+\s+", re.I)
# Dòng mã/JSON ví dụ ("amount": 450000) và câu ví dụ không phải quy định.
_CODE_OR_EXAMPLE = re.compile(r'^[{}\[\]"`]|"\w+"\s*:|^ví dụ\b|^example\b', re.I)
VERDICTS = ("CONTRADICTION", "CONSISTENT", "UNRELATED")


@dataclass(frozen=True)
class Statement:
    sid: str
    source_id: str
    source_name: str
    chunk_id: str
    text: str


def _lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue  # tiêu đề mục, không phải câu quy định
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            line = " · ".join(c for c in cells if c)
        line = re.sub(r"^(#{1,6}|[-*+]|\d+[.)])\s+", "", line)
        out += [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-ZÀ-Ỹ])", line) if s.strip()]
    return out


def extract_statements(chunks: list[SourceChunk], limit: int = 400) -> list[Statement]:
    """Câu có con số hoặc từ quy định, dài 25–320 ký tự, không trùng nội dung trong cùng tài liệu."""
    seen: set[tuple[str, str]] = set()
    out: list[Statement] = []
    for chunk in chunks:
        for line in _lines(chunk.text):
            if not 25 <= len(line) <= 320 or _METADATA.match(line) or _CODE_OR_EXAMPLE.search(line) \
                    or not (re.search(r"\d", _REFERENCE.sub(" ", line)) or _NORMATIVE.search(line)):
                continue
            mark = (chunk.source_id, line.casefold())
            if mark in seen:
                continue
            seen.add(mark)
            out.append(Statement(f"S{len(out) + 1}", chunk.source_id, chunk.source_name, chunk.chunk_id, line))
            if len(out) >= limit:
                return out
    return out


def _topic(text: str) -> set[str]:
    return {t for t in _content_tokens(text) if not any(ch.isdigit() for ch in t) and len(t) > 1}


def candidate_pairs(statements: list[Statement], max_pairs: int = 15, min_overlap: float = 0.3, min_shared: int = 3) -> list[dict]:
    """Cặp câu ở hai tài liệu khác nhau, cùng chủ đề (trùng từ nội dung) nhưng khác con số hoặc khác phủ định.

    Độ trùng = Jaccard trên từ nội dung; khác phủ định dễ nhiễu hơn nên cần trùng gấp rưỡi ngưỡng.
    """
    info = [(s, _topic(s.text), _numbers(_REFERENCE.sub(" ", s.text)), bool(_NEGATION.search(s.text))) for s in statements]
    pairs = []
    for i, (a, ta, na, nega) in enumerate(info):
        for b, tb, nb, negb in info[i + 1:]:
            if a.source_id == b.source_id:
                continue
            shared = ta & tb
            if len(shared) < min_shared:
                continue
            overlap = len(shared) / len(ta | tb)
            reason = ("numbers_differ" if na and nb and na != nb and overlap >= min_overlap
                      else "negation_differs" if nega != negb and overlap >= min_overlap * 1.5 else None)
            if reason:
                pairs.append({"a": asdict(a), "b": asdict(b), "overlap": round(overlap, 3), "reason": reason, "shared_terms": sorted(shared)[:12]})
    pairs.sort(key=lambda p: -p["overlap"])
    picked, per_statement = [], {}
    for p in pairs:  # mỗi câu xuất hiện tối đa 2 lần để danh sách đa dạng
        ids = (p["a"]["sid"], p["b"]["sid"])
        if any(per_statement.get(x, 0) >= 2 for x in ids):
            continue
        for x in ids:
            per_statement[x] = per_statement.get(x, 0) + 1
        picked.append({**p, "pair_id": f"P{len(picked) + 1}"})
        if len(picked) >= max_pairs:
            break
    return picked


# Phạm vi theo từng đối tượng ("cho mỗi merchant", "per user"): khác phạm vi thì khác con số không phải mâu thuẫn.
_SCOPE = re.compile(r"\b(?:cho|trên)\s+mỗi\b|\bmỗi\s+(?:merchant|người|user|tài khoản|khách|kỹ sư|nhân viên)\b|\bper\s+(?:user|merchant|account|customer)\b", re.I)


def unconfirmed_reason(value_a: str, value_b: str, a_text: str, b_text: str) -> str | None:
    """Lý do chưa thể xác nhận một kết luận "mâu thuẫn"; None khi xác nhận được.

    Chỉ tự xác nhận xung đột con số: hai giá trị có thật trong hai câu, khác nhau, và cùng phạm vi.
    Mâu thuẫn không dựa trên con số vẫn hiện cho người duyệt nhưng không được hệ thống tự khẳng định.
    """
    na, nb = _numbers(value_a), _numbers(value_b)
    if not (na and nb):
        return "non_numeric_unverified"
    if not (na <= _numbers(a_text) and nb <= _numbers(b_text)) or na == nb:
        return "unverified_values"
    if bool(_SCOPE.search(a_text)) != bool(_SCOPE.search(b_text)):
        return "different_scope"
    return None


async def judge_pair(provider, a: dict, b: dict) -> dict:
    agent = profile("api_architecture")
    schema = _obj({"verdict": {"type": "string", "enum": list(VERDICTS)}, "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                   "same_subject": {"type": "boolean"}, "value_a": {"type": "string"}, "value_b": {"type": "string"},
                   "explanation": {"type": "string"}})
    system = (
        f"CONSISTENCY_CHECKER. Role={agent['name']}. Two statements come from different documents of the same software project. "
        "CONTRADICTION only when both statements set a rule or value for exactly the same subject and scope, and the values "
        "or rules cannot both hold. Different numbers are NOT a contradiction when they describe different things: a target "
        "versus an alert threshold, a per-user limit versus a system total, an example versus a rule, a whole versus a part. "
        "Examples: 'logs are kept 90 days' vs 'logs are kept 30 days' -> CONTRADICTION; 'response under 2 s (target)' vs "
        "'alert when over 5 s' -> CONSISTENT; 'max 50 files per user' vs 'system stores max 10000 files' -> CONSISTENT. "
        "UNRELATED: different subjects. For a CONTRADICTION copy the conflicting value from each statement into value_a and "
        "value_b. Return JSON only."
    )
    user = (f"STATEMENT A ({a['source_name']}):\n{a['text']}\n\nSTATEMENT B ({b['source_name']}):\n{b['text']}\n\n"
            'Schema: {"verdict":"CONTRADICTION|CONSISTENT|UNRELATED","severity":"HIGH|MEDIUM|LOW","same_subject":true,'
            '"value_a":"giá trị trong A","value_b":"giá trị trong B","explanation":"..."}\n'
            "NGÔN NGỮ: explanation bằng tiếng Việt, một hai câu.")
    obj, measured = await _call(provider, system, user, schema, 350)
    verdict = str(obj.get("verdict") or "").upper()
    flags = []
    if verdict not in VERDICTS:
        verdict, flags = "UNRELATED", ["invalid_model_output"]
    if verdict == "CONTRADICTION" and obj.get("same_subject") is False:
        verdict, flags = "UNRELATED", ["different_subject"]
    elif verdict == "CONTRADICTION" and (reason := unconfirmed_reason(str(obj.get("value_a") or ""), str(obj.get("value_b") or ""), a["text"], b["text"])):
        verdict, flags = "UNRELATED", [reason]
    severity = str(obj.get("severity") or "").upper()
    return {"verdict": verdict, "severity": severity if severity in ("HIGH", "MEDIUM", "LOW") else "LOW",
            "value_a": _text(obj.get("value_a"), 120), "value_b": _text(obj.get("value_b"), 120),
            "explanation": _text(obj.get("explanation"), 400), "flags": flags, **measured}
