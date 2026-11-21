"""Công cụ nghiệp vụ dùng chung cho các ngành: kiểm tra điều kiện của một tình huống, quy trình từng bước.

Mô hình chỉ trích và đối chiếu từng mục kèm mã đoạn; luật cố định ở đây lọc mục thiếu căn cứ và suy ra kết luận
tổng, để kết luận không phụ thuộc lời tự đánh giá của mô hình. Không đi qua planner nên A/B/C giữ nguyên.
"""

from __future__ import annotations

import re
import time

from app.core.citations import validate_citations
from app.core.types import SourceChunk
from app.research.registry import profile

from .traceability import _decode, _numbers, assign_agent

VERDICTS = ("MET", "NOT_MET", "UNKNOWN")
MAX_CONDITIONS = 12
MAX_STEPS = 15


# Số thứ tự cấu trúc ("Điều 10", "Mục 8", dòng "2." / "a)") không phải con số của quy định.
_STRUCTURE = re.compile(r"\b(?:điều|mục|khoản|chương|phần)\s+\d+[a-zđ]?\b|^\s*#*\s*(?:\d{1,2}|[a-zđ])[.)](?=\s)",
                        re.IGNORECASE | re.MULTILINE)


def _rule_text(text: str) -> str:
    return _STRUCTURE.sub(" ", text)


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


def _coverage(part: str, whole: str) -> float:
    words = _words(part)
    return len(words & _words(whole)) / len(words) if words else 0.0


def overall_verdict(conditions: list[dict], removed: int = 0) -> str:
    """Không đạt một điều kiện là không đủ; còn điều kiện chưa xác định là thiếu thông tin; tất cả đạt mới đủ.

    Không còn điều kiện nào: có mục bị loại (thiếu căn cứ, chép từ tình huống) là UNRESOLVED, không có gì là NO_RULE.
    """
    if not conditions:
        return "UNRESOLVED" if removed else "NO_RULE"
    verdicts = {c["verdict"] for c in conditions}
    if "NOT_MET" in verdicts:
        return "NOT_ELIGIBLE"
    if "UNKNOWN" in verdicts:
        return "INSUFFICIENT_INFO"
    return "ELIGIBLE"


def _evidence_block(evidence: list[SourceChunk]) -> str:
    return "\n\n".join(f"[{c.chunk_id}] ({c.source_name})\n{c.text}" for c in evidence)


def _evidence_meta(evidence: list[SourceChunk]) -> list[dict]:
    return [{"chunk_id": c.chunk_id, "source_name": c.source_name, "score": round(float(c.score or 0), 4)} for c in evidence]


# 21/11: danh sách điều kiện dài vượt 700 token mặc định → JSON bị cắt, kết quả rỗng ("Chưa trích được điều kiện")
COND_MAX_TOKENS = 1400


def _lang(text: str) -> str:
    """Câu hỏi tiếng Việt thì mọi ô viết tiếng Việt (mô hình 4B hay viết phần giải thích bằng tiếng Anh)."""
    from app.research.pipeline import reply_language_of  # nhập muộn tránh vòng import
    return ("Write every text field (condition, case_fact, reason, note, action, actor) in Vietnamese."
            if reply_language_of(text) == "vi" else "Write every text field in English.")


async def _ask(provider, system: str, user: str, schema: dict, max_tokens: int | None = None):
    structured = getattr(provider, "generate_structured", None)
    if not callable(structured):
        return await provider.generate(system=system, user=user)
    # 21/11: mặc định 700 token cắt giữa JSON (ngưỡng, quy trình, điều kiện) → kết quả rỗng; công cụ phân tích dùng tối thiểu 1.400
    if getattr(provider, "supports_per_call_output_tokens", False):
        extra = {"max_output_tokens": max(max_tokens or 0, COND_MAX_TOKENS)}
    else:
        extra = {"max_output_tokens": max_tokens} if max_tokens else {}
    return await structured(system=system, user=user, response_schema=schema, **extra)


_ABSENT = re.compile(r"^\s*(?:không|chưa)\s+(?:có|nêu|quy định|rõ|xác định)|^\s*(?:n/?a|none|không)\s*\.?$", re.IGNORECASE)


def _present(text: str) -> str:
    """Ô mô hình điền "Không có thông tin…" thì coi như để trống."""
    return "" if _ABSENT.search(text or "") else text


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    return {"input_tokens": int(getattr(usage, "input_tokens", 0) or 0), "output_tokens": int(getattr(usage, "output_tokens", 0) or 0)}


def _text(value: object, limit: int = 400) -> str:
    return " ".join(str(value or "").split())[:limit]


# So con số bằng luật cố định (thử theo vai 20/11: "ĐTB từ 3,2 và rèn luyện từ 70" với tình huống "ĐTB 3,4; rèn luyện 65"
# bị mô hình kết luận "chưa rõ"). Mỗi vế "<tên> từ N trở lên / dưới N / tối đa N" được so với số đứng sau tên đó trong
# tình huống. Thiếu số của vế nào thì không kết luận (giữ nhận định của mô hình).
_CLAUSE_SPLIT = re.compile(r"\s+và\s+|;|,\s+(?=[^\d])")
_THRESH = re.compile(r"(?P<label>[^\d]{2,60}?)\s+(?P<op>từ|tối thiểu|ít nhất|không dưới|trên|dưới|tối đa|không quá|nhỏ hơn|lớn hơn)\s+(?P<num>\d+(?:[.,]\d+)?)", re.I)
_OPS = {"từ": ">=", "tối thiểu": ">=", "ít nhất": ">=", "không dưới": ">=", "trên": ">", "lớn hơn": ">",
        "dưới": "<", "nhỏ hơn": "<", "tối đa": "<=", "không quá": "<="}


def _num(v: str) -> float:
    return float(v.replace(",", "."))


def numeric_verdict(condition: str, case: str) -> str | None:
    from app.retrieval.hybrid import fold
    folded_case = fold(case)
    if re.search(r"\bkhong\b|\bchua\b|\bcam\b", fold(condition)):
        return None  # điều kiện phủ định hoặc loại trừ ("không được xét nếu…"): không so số, giữ nhận định ban đầu
    results = []
    for clause in _CLAUSE_SPLIT.split(condition):
        m = _THRESH.search(clause)
        if not m:
            continue
        words = [w for w in re.findall(r"[a-z]+", fold(m.group("label"))) if len(w) > 1 and w not in {"sinh", "vien", "co", "duoc", "khi", "la", "phai"}]
        if not words:
            continue
        key = r"\s+".join(words[-2:])  # hai chữ cuối của tên tiêu chí ("trung binh", "ren luyen")
        hit = re.search(key + r"[^\d;]{0,25}?(\d+(?:[.,]\d+)?)", folded_case)
        if not hit:
            return None
        if re.search(r"\b(khong|chua)\b", folded_case[max(0, hit.start() - 20):hit.end()]):
            return None  # tình huống phủ định ("không có học phần dưới 5"): không đọc thành con số
        value, target, op = _num(hit.group(1)), _num(m.group("num")), _OPS[m.group("op").lower()]
        ok = {">=": value >= target, ">": value > target, "<": value < target, "<=": value <= target}[op]
        results.append(ok)
    if not results:
        return None
    return "MET" if all(results) else "NOT_MET"


_SUBJECT = re.compile(r"\b(duoc|dieu kien|tieu chuan|huong|xin)\s+([a-z ]+?)(?=\s+\d|\s+khong\b|\s+(neu|khi|trong|tai)\b|[?.,;]|$)")


def question_subject(question: str) -> list[str]:
    """Chủ đề của câu hỏi điều kiện: phần sau "được / đủ điều kiện / hưởng / xin" tới con số hoặc "không".
    "Có được nghỉ phép 6 ngày không?" → ["nghi_phep"]; "Có đủ điều kiện học bổng không?" → ["hoc_bong"]."""
    from app.retrieval.hybrid import _STOP, fold
    m = _SUBJECT.search(fold(question))
    if not m:
        return []
    words = [w for w in m.group(2).split() if w not in _STOP and len(w) > 1][:3]
    return [f"{x}_{y}" for x, y in zip(words, words[1:])] or words


def mentions_question(question: str, evidence: list[SourceChunk]) -> bool:
    """Đoạn quy định có nói tới chủ đề của câu hỏi không. Dùng để không ép mô hình tìm điều kiện trong tài liệu không
    liên quan (P1-1, 20/11). Không tách được chủ đề thì coi là có (giữ hành vi cũ: hỏi lại một lần)."""
    from app.retrieval.hybrid import tokens
    subject = question_subject(question)
    if not subject:
        return True
    return bool(set(subject) & set(tokens(" ".join(c.text for c in evidence))))


async def check_conditions(provider, question: str, case: str, evidence: list[SourceChunk]) -> dict:
    started = time.perf_counter()
    _, agent_id = assign_agent(f"{question}\n{case}")
    agent = profile(agent_id)
    base = {"agent": agent_id, "agent_name": agent["name"], "evidence": _evidence_meta(evidence), "conditions": [],
            "removed": 0, "note": "", "input_tokens": 0, "output_tokens": 0}
    if not evidence:
        return {**base, "overall": "NO_RULE", "note": "Không tìm thấy đoạn quy định nào liên quan trong tài liệu đã chọn.",
                "latency_ms": int((time.perf_counter() - started) * 1000)}
    if not mentions_question(question, evidence):
        # P1-1: các đoạn tìm được không nói tới chủ đề câu hỏi (vd. hỏi nghỉ phép trong kho tài liệu kỹ thuật):
        # báo không có quy định, không gọi mô hình để khỏi ép nó "tìm" điều kiện trong tài liệu không liên quan
        return {**base, "overall": "NO_RULE", "note": "Các đoạn tìm được trong tài liệu đã chọn không nói tới nội dung câu hỏi.",
                "latency_ms": int((time.perf_counter() - started) * 1000)}
    ids = [c.chunk_id for c in evidence]
    system = (
        f"CONDITION_CHECKER. Role={agent['name']}. Scope={agent['scope']}. "
        "From the RULE EVIDENCE list every condition that the QUESTION depends on, copying each condition faithfully "
        "with its numbers, and cite the chunk that states it. For each condition compare it with the CASE: "
        "MET if the case clearly satisfies it, NOT_MET if the case clearly violates it, UNKNOWN if the case does not say. "
        "case_fact must quote what the CASE says about that condition, or be empty. Conditions are rules written in the "
        "RULE EVIDENCE; never turn facts from the CASE into conditions. Do not invent facts or conditions. "
        "List at most 6 conditions, only rules that directly decide the QUESTION (skip unrelated rules such as discipline or sales targets). "
        + _lang(question) + " Return JSON only."
    )
    # quy định đứng trước tình huống: mô hình nhỏ ít chép dữ kiện thành điều kiện hơn
    user = f"RULE EVIDENCE:\n{_evidence_block(evidence)}\n\nQUESTION: {question}\n\nCASE:\n{case}"
    schema = {
        "type": "object",
        "properties": {
            "conditions": {"type": "array", "items": {"type": "object", "properties": {
                "condition": {"type": "string"}, "citation": {"type": "string", "enum": ids},
                "case_fact": {"type": "string"}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                "reason": {"type": "string"}}, "required": ["condition", "citation", "case_fact", "verdict", "reason"],
                "additionalProperties": False}},
            "note": {"type": "string"},
        },
        "required": ["conditions", "note"], "additionalProperties": False,
    }
    response = await _ask(provider, system, user, schema)
    usage = _usage(response)
    obj = _decode(response.text)
    conditions, removed, copied = _grounded_conditions(obj, case, evidence)
    if not conditions and (copied or not obj.get("conditions")):
        # mô hình chỉ lặp lại tình huống hoặc trả rỗng (mô hình nhỏ hay dao động): hỏi lại đúng một lần
        why = (f"REJECTED (facts from the CASE, not rules): {'; '.join(copied)}" if copied
               else "Your previous answer listed no conditions, but the RULE EVIDENCE above contains rules related to the QUESTION.")
        retry = f"{user}\n\n{why}\nList the rules from the RULE EVIDENCE that decide the QUESTION, then compare each with the CASE."
        response = await _ask(provider, system, retry, schema)
        usage = {k: usage[k] + v for k, v in _usage(response).items()}
        obj = _decode(response.text)
        conditions, more, _ = _grounded_conditions(obj, case, evidence)
        removed += more
    for c in conditions:
        ruled = numeric_verdict(c["condition"], case)
        if ruled and ruled != c["verdict"]:  # phép so con số do luật cố định làm, thay nhận định của mô hình
            c["verdict"], c["flags"] = ruled, [*c["flags"], "numeric_rule"]
            c["reason"] = (c["reason"] + " " if c["reason"] else "") + "(So con số theo luật cố định.)"
    return {**base, **usage, "conditions": conditions, "removed": removed, "overall": overall_verdict(conditions, removed) if conditions else "UNRESOLVED",  # có đoạn quy định mà không trích được điều kiện
            "note": _text(obj.get("note"), 500), "latency_ms": int((time.perf_counter() - started) * 1000)}


def _grounded_conditions(obj: dict, case: str, evidence: list[SourceChunk]) -> tuple[list[dict], int, list[str]]:
    """Điều kiện còn lại sau luật cố định, số mục bị loại, và các "điều kiện" chép từ tình huống."""
    by_id = {c.chunk_id: c for c in evidence}
    case_numbers = _numbers(case)
    conditions, removed, copied = [], 0, []
    for raw in obj.get("conditions") or []:
        if not isinstance(raw, dict) or not _text(raw.get("condition")):
            continue
        valid, _ = validate_citations([str(raw.get("citation") or "")], evidence)
        if not valid:
            removed += 1  # điều kiện không có căn cứ trong tài liệu: không dùng để kết luận
            continue
        item = {"condition": _text(raw.get("condition")), "citation": valid[0], "case_fact": _text(raw.get("case_fact")),
                "verdict": str(raw.get("verdict") or "").upper(), "reason": _text(raw.get("reason")), "flags": []}
        if item["verdict"] not in VERDICTS:
            item["verdict"], item["flags"] = "UNKNOWN", ["invalid_model_output"]
        targets = _numbers(_rule_text(item["condition"]))
        if targets - _numbers(_rule_text(by_id[item["citation"]].text)):
            # mô hình nhỏ hay dẫn nhầm đoạn bên cạnh: đoạn đã đọc nào chứa đủ con số thì dẫn đoạn đó
            fix = next((c for c in evidence if not targets - _numbers(_rule_text(c.text))), None)
            if fix is not None:
                item["citation"] = fix.chunk_id
                item["flags"].append("citation_corrected")
            else:
                item["verdict"] = "UNKNOWN"
                item["flags"].append("numbers_not_in_source")
        source = _rule_text(by_id[item["citation"]].text)
        in_case, in_rule = _coverage(item["condition"], case), _coverage(_rule_text(item["condition"]), source)
        if in_case >= 0.8 and in_case > in_rule:
            removed += 1  # "điều kiện" chép từ tình huống chứ không phải quy định trong tài liệu
            copied.append(item["condition"])
            continue
        if item["verdict"] != "UNKNOWN" and not item["case_fact"]:
            item["verdict"] = "UNKNOWN"
            item["flags"].append("no_case_fact")
        if item["verdict"] != "UNKNOWN" and _numbers(item["case_fact"]) - case_numbers:
            item["verdict"] = "UNKNOWN"  # dữ kiện mô hình tự thêm, không có trong tình huống
            item["flags"].append("fact_not_in_case")
        conditions.append(item)
        if len(conditions) == MAX_CONDITIONS:
            break
    return conditions, removed, copied


async def extract_procedure(provider, topic: str, evidence: list[SourceChunk]) -> dict:
    started = time.perf_counter()
    _, agent_id = assign_agent(topic)
    agent = profile(agent_id)
    base = {"agent": agent_id, "agent_name": agent["name"], "evidence": _evidence_meta(evidence), "steps": [],
            "documents": [], "fees": [], "removed": 0, "note": "", "input_tokens": 0, "output_tokens": 0}
    if not evidence:
        return {**base, "note": "Không tìm thấy đoạn nào mô tả quy trình này trong tài liệu đã chọn.",
                "latency_ms": int((time.perf_counter() - started) * 1000)}
    ids = [c.chunk_id for c in evidence]
    system = (
        f"PROCEDURE_EXTRACTOR. Role={agent['name']}. Scope={agent['scope']}. "
        "Using only the EVIDENCE, list the steps of the requested PROCEDURE in order. For each step give the action, "
        "who performs or approves it, the time limit and the papers or outputs, exactly as the evidence states; leave a "
        "field empty when the evidence does not say. Cite the chunk for every step. Also list only the papers the "
        "evidence says must be submitted for THIS procedure, each with a citation (empty if none), and any fees or charges "
        "exactly as stated, each with a citation (empty if none). Do not invent steps. Keep every field short (under 25 words, a paper is its name only); at most 8 steps and 10 papers. "
        + _lang(topic) + " Return JSON only."
    )
    user = f"PROCEDURE: {topic}\n\nEVIDENCE:\n{_evidence_block(evidence)}"
    schema = {
        "type": "object",
        "properties": {
            "steps": {"type": "array", "items": {"type": "object", "properties": {
                "action": {"type": "string"}, "actor": {"type": "string"}, "deadline": {"type": "string"},
                "outputs": {"type": "string"}, "citation": {"type": "string", "enum": ids}},
                "required": ["action", "actor", "deadline", "outputs", "citation"], "additionalProperties": False}},
            "documents": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "citation": {"type": "string", "enum": ids}},
                "required": ["name", "citation"], "additionalProperties": False}},
            "fees": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "citation": {"type": "string", "enum": ids}},
                "required": ["text", "citation"], "additionalProperties": False}},
            "note": {"type": "string"},
        },
        "required": ["steps", "documents", "fees", "note"], "additionalProperties": False,
    }
    response = await _ask(provider, system, user, schema, max_tokens=2400 if getattr(provider, "supports_per_call_output_tokens", False) else None)
    obj = _decode(response.text)
    by_id = {c.chunk_id: c for c in evidence}
    steps, removed = [], 0
    for raw in obj.get("steps") or []:
        if not isinstance(raw, dict) or not _text(raw.get("action")):
            continue
        valid, _ = validate_citations([str(raw.get("citation") or "")], evidence)
        if not valid:
            removed += 1  # bước không có căn cứ: bỏ, không đoán
            continue
        step = {"order": len(steps) + 1, "action": _text(raw.get("action")), "actor": _present(_text(raw.get("actor"), 160)),
                "deadline": _present(_text(raw.get("deadline"), 160)), "outputs": _present(_text(raw.get("outputs"), 240)),
                "citation": valid[0], "flags": []}
        source = _rule_text(by_id[valid[0]].text)
        if step["deadline"] and _numbers(step["deadline"]) - _numbers(source):
            step["deadline"] = ""  # thời hạn có con số không nằm trong đoạn trích: không hiển thị
            step["flags"].append("deadline_not_in_source")
        steps.append(step)
        if len(steps) == MAX_STEPS:
            break
    documents, seen = [], set()
    for raw in obj.get("documents") or []:
        name = _text(raw.get("name"), 200) if isinstance(raw, dict) else ""
        valid, _ = validate_citations([str(raw.get("citation") or "")], evidence) if name else ([], [])
        if name and not valid:
            removed += 1  # giấy tờ không có căn cứ: bỏ
        elif name and name.casefold() not in seen:
            seen.add(name.casefold())
            documents.append({"name": name, "citation": valid[0]})
    fees = []
    for raw in obj.get("fees") or []:
        text = _text(raw.get("text"), 240) if isinstance(raw, dict) else ""
        valid, _ = validate_citations([str(raw.get("citation") or "")], evidence) if text else ([], [])
        # lệ phí phải có căn cứ và mọi con số phải có trong đoạn được dẫn
        if text and valid and not _numbers(_rule_text(text)) - _numbers(_rule_text(by_id[valid[0]].text)):
            fees.append({"text": text, "citation": valid[0]})
        elif text:
            removed += 1
    return {**base, **_usage(response), "steps": steps, "documents": documents, "fees": fees, "removed": removed,
            "note": _text(obj.get("note"), 500), "latency_ms": int((time.perf_counter() - started) * 1000)}
