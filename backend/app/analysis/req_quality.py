"""Soát chất lượng yêu cầu theo các đặc tính của ISO/IEC/IEEE 29148:2018 (mục 5.2.5).

Phần soát là luật xác định (không gọi mô hình): cùng tài liệu luôn cho cùng kết quả, mỗi lỗi chỉ ra đúng cụm chữ vi phạm
và lý do, nên kiểm lại được bằng tay. Luật được chọn để ít báo nhầm trên tài liệu viết tốt (ví dụ "có thể" chỉ quyền
được làm nên không bị coi là lời lẽ yếu; "cao/thấp" chỉ bị báo khi câu không có con số nào).
Phần "đề xuất viết lại" mới gọi mô hình, và bị cấm tự đặt con số: chỗ cần số phải để trống dạng [cần xác định: ...].
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.analysis.design import _call, _obj, _text
from app.analysis.evaluation import _content_tokens
from app.analysis.traceability import Requirement, extract_requirements

STANDARD = "ISO/IEC/IEEE 29148:2018, mục 5.2.5 (đặc tính của từng yêu cầu)"

# Đặc tính theo 29148 (tên tiếng Việt dùng trên giao diện).
CHARACTERISTICS = {
    "unambiguous": "Rõ nghĩa (Unambiguous)",
    "verifiable": "Kiểm chứng được (Verifiable)",
    "singular": "Đơn nhất (Singular)",
    "complete": "Đầy đủ (Complete)",
    "feasible": "Khả thi (Feasible)",
    "necessary": "Cần thiết, không trùng (Necessary)",
    "conforming": "Đúng quy ước viết (Conforming)",
}


@dataclass(frozen=True)
class Rule:
    rule: str
    label: str
    characteristic: str
    severity: str  # error | warning | info
    message: str
    suggestion: str


RULES = {r.rule: r for r in [
    Rule("tbd", "Còn chỗ chưa xác định", "complete", "error",
         "Yêu cầu còn đánh dấu chưa xong (TBD, chưa xác định...).", "Chốt nội dung còn thiếu hoặc ghi rõ ai quyết định và hạn chót."),
    Rule("vague", "Từ ngữ mơ hồ", "unambiguous", "warning",
         "Từ này mỗi người hiểu một kiểu, không kiểm thử được.", "Thay bằng tiêu chí đo được (con số, đơn vị, điều kiện cụ thể)."),
    Rule("unmeasured", "Yêu cầu chất lượng thiếu con số", "verifiable", "warning",
         "Yêu cầu về hiệu năng / sẵn sàng / tải... nhưng không có chỉ tiêu định lượng.", "Thêm chỉ tiêu: giá trị, đơn vị, điều kiện đo (ví dụ: 95% yêu cầu dưới 300 ms ở 200 yêu cầu/giây)."),
    Rule("compound", "Gộp nhiều nghĩa vụ trong một câu", "singular", "warning",
         "Một câu chứa nhiều nghĩa vụ (nhiều \"phải\" hoặc \"và/hoặc\"), khó truy vết và kiểm thử riêng.", "Tách thành các câu, mỗi câu một nghĩa vụ."),
    Rule("weak", "Lời lẽ không bắt buộc", "conforming", "warning",
         "Dùng từ khuyến nghị (nên, cố gắng, should...) nên không rõ đây có phải yêu cầu bắt buộc.", "Dùng \"phải\" nếu bắt buộc; nếu chỉ là mong muốn thì ghi rõ mức ưu tiên."),
    Rule("open_list", "Liệt kê bỏ ngỏ", "complete", "warning",
         "Danh sách kết thúc bằng v.v. / ... / etc. nên phạm vi không rõ.", "Liệt kê đủ các mục hoặc dẫn tới danh mục đầy đủ."),
    Rule("duplicate", "Trùng với yêu cầu khác", "necessary", "warning",
         "Nội dung gần như trùng với một yêu cầu khác.", "Gộp hai yêu cầu hoặc nêu rõ điểm khác nhau."),
    Rule("absolute", "Từ tuyệt đối", "feasible", "info",
         "Từ tuyệt đối (luôn luôn, không bao giờ...) thường khó đạt và khó chứng minh.", "Kiểm tra có thật sự cần tuyệt đối không; nếu không, nêu ngưỡng chấp nhận."),
    Rule("long", "Câu quá dài", "singular", "info",
         "Câu dài trên 60 từ dễ chứa nhiều ý.", "Tách câu hoặc chuyển chi tiết sang bảng."),
    Rule("reference", "Tham chiếu mơ hồ", "unambiguous", "info",
         "Tham chiếu kiểu \"như trên\", \"tương tự\" không chỉ rõ tới đâu.", "Ghi mã yêu cầu hoặc mục được tham chiếu."),
]}

_W = r"(?<![\w])"  # đầu từ (\b của Python coi chữ có dấu là chữ, dùng được với tiếng Việt)
_E = r"(?![\w])"


def _words(*items: str) -> re.Pattern:
    # cụm dài trước để "nhanh chóng" không bị khớp thành "nhanh"
    return re.compile(_W + "(" + "|".join(sorted(items, key=len, reverse=True)) + ")" + _E, re.IGNORECASE)


_TBD = re.compile(r"(?<![\w])(TBD|TBA|TODO|chưa xác định|sẽ bổ sung( sau)?|sẽ cập nhật( sau)?|đang cập nhật)(?![\w])|\?{2,}|(?<![\w])x{2,}(?![\w])", re.IGNORECASE)
_VAGUE = _words(
    "nhanh", "nhanh chóng", "kịp thời", "thân thiện", "dễ dùng", "dễ sử dụng", "trực quan", "linh hoạt", "hiệu quả",
    "tối ưu", "phù hợp", "hợp lý", "ổn định", "mạnh mẽ", "hiện đại", "chuyên nghiệp", "tốt hơn", "tốt nhất", "tương đối",
    "đáng kể", "tối thiểu hóa", "tối đa hóa", "một số", "đa dạng", "xấp xỉ",
    "fast", "quick(ly)?", "user[- ]friendly", "easy", "intuitive", "flexible", "efficient(ly)?", "optimal", "appropriate",
    "reasonable", "robust", "adequate", "several", "approximately", "as soon as possible", "minimi[sz]e", "maximi[sz]e")
_VAGUE_NO_NUMBER = _words("cao", "thấp", "lớn", "nhỏ", "nhiều", "high", "low", "large", "small", "many", "some")
_QUALITY = _words(
    "hiệu năng", "thời gian phản hồi", "độ trễ", "chịu tải", "tải", "đồng thời", "sẵn sàng", "khả dụng", "mở rộng",
    "thông lượng", "uptime", "performance", "latency", "response time", "throughput", "availability", "scalab\\w*", "concurrent")
_STRONG = _words("phải", "bắt buộc", "không được", "shall", "must")
_AND_OR = re.compile(r"(?<![\w])(và/hoặc|and/or)(?![\w])", re.IGNORECASE)
_WEAK = _words("nên", "cố gắng", "nếu có thể", "khi có thể", "mong muốn", "should", "may", "might", "could", "ideally")
_OPEN = re.compile(r"(?<![\w])(v\.v\.?|vv\.|etc\.?|bao gồm nhưng không giới hạn)|…|\.\.\.", re.IGNORECASE)
_ABSOLUTE = _words("luôn luôn", "không bao giờ", "tuyệt đối", "mãi mãi", "bất kỳ lúc nào", "always", "never", "under no circumstances")
_REFERENCE = _words("như trên", "như đã nêu", "như đã nói", "tương tự như", "như mục trên", "xem phần khác", "as above", "as mentioned")
_DIGIT = re.compile(r"\d")
_SENTENCE = re.compile(r"(?<=[.;!?])\s+|\n+")


def _statements(req: Requirement) -> list[str]:
    """Các câu/gạch đầu dòng của yêu cầu (bỏ ký hiệu đầu dòng và dòng kẻ bảng)."""
    out = []
    for part in _SENTENCE.split(f"{req.title}\n{req.body}"):
        s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", part).strip(" |")
        if s and not re.fullmatch(r"[-|:\s]+", s):
            out.append(s)
    return out


def _issue(rule: str, evidence: str, **extra) -> dict:
    r = RULES[rule]
    return {"rule": r.rule, "label": r.label, "characteristic": r.characteristic,
            "characteristic_label": CHARACTERISTICS[r.characteristic], "severity": r.severity,
            "evidence": evidence[:160], "message": r.message, "suggestion": r.suggestion, **extra}


def check_requirement(req: Requirement) -> list[dict]:
    issues: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(rule: str, evidence: str, **extra):
        key = (rule, evidence.lower())
        if key not in seen:
            seen.add(key)
            issues.append(_issue(rule, evidence, **extra))

    statements = _statements(req)
    whole = " ".join(statements)
    for s in statements:
        for m in _TBD.finditer(s):
            add("tbd", m.group(0))
        for m in _VAGUE.finditer(s):
            add("vague", m.group(0))
        if not _DIGIT.search(s):
            for m in _VAGUE_NO_NUMBER.finditer(s):
                add("vague", m.group(0))
        strong = _STRONG.findall(s)
        if len(strong) >= 2 or _AND_OR.search(s):
            add("compound", s)
        for m in _WEAK.finditer(s):
            add("weak", m.group(0))
        for m in _OPEN.finditer(s):
            add("open_list", m.group(0))
        for m in _ABSOLUTE.finditer(s):
            add("absolute", m.group(0))
        if len(s.split()) > 60:
            add("long", s[:80] + "…")
        for m in _REFERENCE.finditer(s):
            add("reference", m.group(0))
    is_quality = req.req_id.upper().startswith("NFR") or bool(_QUALITY.search(whole))
    if is_quality and not _DIGIT.search(whole):
        found = _QUALITY.search(whole)
        add("unmeasured", found.group(0) if found else req.title or req.req_id)
    return issues


def _similar(a: Requirement, b: Requirement) -> float:
    ta, tb = set(_content_tokens(f"{a.title} {a.body}")), set(_content_tokens(f"{b.title} {b.body}"))
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def review_text(text: str, *, duplicate_threshold: float = 0.8) -> dict:
    requirements = extract_requirements(text)
    rows = [{"req_id": r.req_id, "title": r.title, "text": f"{r.title}\n{r.body}".strip(), "issues": check_requirement(r)}
            for r in requirements]
    for i, a in enumerate(requirements):
        for j in range(i + 1, len(requirements)):
            b = requirements[j]
            if _similar(a, b) >= duplicate_threshold:
                rows[j]["issues"].append(_issue("duplicate", a.req_id, other=a.req_id))
                rows[i]["issues"].append(_issue("duplicate", b.req_id, other=b.req_id))
    by_rule: dict[str, int] = {}
    by_char: dict[str, int] = {}
    for row in rows:
        for issue in row["issues"]:
            by_rule[issue["rule"]] = by_rule.get(issue["rule"], 0) + 1
            by_char[issue["characteristic"]] = by_char.get(issue["characteristic"], 0) + 1
    # "đạt" = không có lỗi hay cảnh báo (mục "lưu ý" chỉ để người viết cân nhắc)
    clean = sum(1 for row in rows if not any(i["severity"] in ("error", "warning") for i in row["issues"]))
    return {
        "standard": STANDARD,
        "rules": [{"rule": r.rule, "label": r.label, "characteristic": r.characteristic,
                   "characteristic_label": CHARACTERISTICS[r.characteristic], "severity": r.severity} for r in RULES.values()],
        "requirements": rows,
        "summary": {"total": len(rows), "clean": clean, "with_issues": len(rows) - clean,
                    "errors": sum(1 for row in rows for i in row["issues"] if i["severity"] == "error"),
                    "warnings": sum(1 for row in rows for i in row["issues"] if i["severity"] == "warning"),
                    "infos": sum(1 for row in rows for i in row["issues"] if i["severity"] == "info"),
                    "by_rule": by_rule, "by_characteristic": by_char},
    }


_SPLIT_BEFORE_OBLIGATION = re.compile(r"\s*(?:,|;|\bvà\b|\band\b)\s+(?=[^,;]*?" + _STRONG.pattern + r")", re.IGNORECASE)


def obligations(text: str) -> list[str]:
    """Tách yêu cầu thành từng nghĩa vụ bằng luật: mỗi câu/gạch đầu dòng, rồi cắt trước vế "và ... phải ..." có nghĩa vụ riêng.

    Làm bằng luật (không nhờ mô hình) để mô hình nhỏ không bỏ sót ý khi viết lại.
    """
    out: list[str] = []
    for part in _SENTENCE.split(text):
        s = re.sub(r"^\s*(?:[-*+]|\d+[.)]|\|)\s*", "", part).strip(" |.")
        if not s or re.fullmatch(r"[-|:\s]+", s):
            continue
        pieces = [p.strip(" ,;.") for p in _SPLIT_BEFORE_OBLIGATION.split(s)]
        out += [p for p in pieces if len(p.split()) >= 2]
    return out[:12]


async def suggest_rewrite(provider, req_id: str, text: str, issues: list[str]) -> dict:
    """Mô hình viết lại TỪNG nghĩa vụ đã tách sẵn; không được tự đặt con số, chỗ thiếu số để [cần xác định: ...].

    Sau đó bản viết lại được soát lại bằng chính bộ luật: còn từ mơ hồ / thiếu số đo ở đâu thì báo ra (remaining).
    """
    items = (obligations(text) or [text.strip()[:600]])[:MAX_OBLIGATIONS]
    schema = _obj({"text": {"type": "string"}, "question": {"type": "string"}})
    system = ("REQUIREMENTS_EDITOR. Rewrite ONE obligation of a software requirement as one statement that follows "
              "ISO/IEC/IEEE 29148: singular, unambiguous, verifiable, uses 'phải' for a mandatory obligation, keeps the meaning, "
              "identifiers, numbers and units exactly. NEVER invent numbers, limits, durations or names: where a measurable "
              "value is needed but not given, write a placeholder like [cần xác định: thời gian phản hồi tối đa]. If the author "
              "must decide something, write it as one complete Vietnamese question; otherwise leave question empty. Return JSON only.")
    rewrites: list[str] = []
    missing: list[str] = []
    questions: list[str] = []
    measured = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}
    # mỗi nghĩa vụ một lần gọi: mô hình nhỏ gộp hay bỏ sót ý khi nhận cả danh sách
    for item in items:
        related = [i for i in issues if any(w and w.lower() in item.lower() for w in i.split(": ", 1)[1:])] or issues
        user = (f"REQUIREMENT {req_id}\nOBLIGATION:\n{item}\n\nDETECTED PROBLEMS:\n- " + "\n- ".join(related[:8]) + "\n\n"
                'Schema: {"text":"nghĩa vụ đã viết lại","question":"câu hỏi cho tác giả? hoặc để trống"}\nNGÔN NGỮ: tiếng Việt.')
        obj, m = await _call(provider, system, user, schema, 400)
        for k in measured:
            measured[k] += int(m.get(k, 0) or 0)
        t = _text(obj.get("text"), 600)
        (rewrites if t else missing).append(t or item)
        q = _text(obj.get("question"), 300)
        if q.endswith("?") and q not in questions:
            questions.append(q)
    if not rewrites:
        raise ValueError("Mô hình không đưa ra được cách viết lại.")
    # soát lại bản viết lại bằng chính bộ luật; chỗ để trống [cần xác định: ...] coi như đã có số (tác giả sẽ điền)
    recheck = check_requirement(Requirement(req_id, "", "\n".join(re.sub(r"\[cần xác định:[^\]]*\]", "0", t) for t in rewrites), [], ""))
    return {"req_id": req_id, "obligations": items, "rewrites": rewrites, "missing": missing,
            "remaining": [f"{i['label']}: {i['evidence']}" for i in recheck if i["severity"] != "info"],
            "open_questions": questions[:8],
            # con số trong bản viết lại mà bản gốc không có: báo để người dùng soát (mô hình bị cấm bịa số)
            "new_numbers": sorted(set(re.findall(r"\d+(?:[.,]\d+)?", " ".join(rewrites))) - set(re.findall(r"\d+(?:[.,]\d+)?", text))),
            **measured}


MAX_OBLIGATIONS = 6  # giới hạn số lần gọi mô hình cho một yêu cầu (mỗi lần ~2 giây trên GPU)


_STR_OBJ = _obj({"text": {"type": "string"}})
