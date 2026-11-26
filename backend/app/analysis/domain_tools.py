"""Công cụ riêng theo ngành (Giáo dục, Doanh nghiệp – Nhân sự, Hành chính – Pháp lý).

Nguyên tắc: mô hình chỉ trích thông tin từ tài liệu kèm mã đoạn; phép so sánh, tính toán và kết luận do mã cố định
ở đây làm. Mục nào không có căn cứ hợp lệ thì bỏ hoặc gắn cờ, không đoán. Không đi qua planner nên A/B/C giữ nguyên.
"""

from __future__ import annotations

import csv
import io
import math
import re
import time
import unicodedata
from datetime import date

from app.core.citations import validate_citations
from app.core.types import SourceChunk
from app.ingestion.documents import DocumentTypeError, xlsx_sheets
from app.research.registry import profile

from .casework import _ask, _coverage, _evidence_block, _evidence_meta, _rule_text, _text, _usage
from .traceability import _decode, _numbers, assign_agent, bm25_rank

MAX_TABLE_ROWS = 2000
MAX_TABLE_COLS = 40
OPS = (">=", ">", "<=", "<", "=")


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _cited(raw_citation: object, evidence: list[SourceChunk]) -> str | None:
    valid, _ = validate_citations([str(raw_citation or "")], evidence)
    return valid[0] if valid else None


def _number(value: object) -> float | None:
    """Số trong ô bảng hoặc chuỗi: '3,4' / '3.4' / '1.200.000' / '75%'; không đọc được thì None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    text = str(value or "").strip().replace(" ", "").rstrip("%")
    if not text:
        return None
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?", text):  # 1.200.000 hoặc 1.200.000,5
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):  # 1,200,000
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _fmt(number: float) -> str:
    return f"{number:g}".replace(".", ",")


def _value_in(value: float, text: str) -> bool:
    """Giá trị số có xuất hiện trong đoạn quy định không (bỏ số thứ tự Điều/Mục)."""
    return any(abs(value - (_number(n) or math.nan)) < 1e-9 for n in _numbers(_rule_text(text)))


# ------------------------------------------------------------------ bảng dữ liệu (Excel/CSV)
def parse_table(data: bytes, filename: str) -> dict:
    """Bảng đầu tiên của tệp: hàng đầu là tiêu đề cột. Hỗ trợ .xlsx và .csv (UTF-8, dấu phẩy hoặc chấm phẩy)."""
    name = (filename or "").casefold()
    if name.endswith(".xlsx"):
        sheets = [rows for _, rows in xlsx_sheets(data) if rows]
        if not sheets:
            raise DocumentTypeError("XLSX contains no cell values")
        rows = sheets[0]
    elif name.endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentTypeError("CSV must be UTF-8") from exc
        dialect = ";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ","
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=dialect) if any(c.strip() for c in r)]
    else:
        raise DocumentTypeError("Chỉ nhận bảng .xlsx hoặc .csv")
    if len(rows) < 2:
        raise DocumentTypeError("Bảng cần một hàng tiêu đề và ít nhất một hàng dữ liệu")
    width = min(MAX_TABLE_COLS, max(len(r) for r in rows))
    header = [(rows[0][i] if i < len(rows[0]) else "") or f"Cột {i + 1}" for i in range(width)]
    body = [[(r[i] if i < len(r) else "") for i in range(width)] for r in rows[1:MAX_TABLE_ROWS + 1]]
    return {"columns": header, "rows": body, "truncated": len(rows) - 1 > MAX_TABLE_ROWS}


# ------------------------------------------------------------------ Giáo dục: ngưỡng xét duyệt + xét theo danh sách
async def extract_thresholds(provider, topic: str, evidence: list[SourceChunk]) -> dict:
    """Ngưỡng số của một loại xét duyệt (học bổng, tốt nghiệp, cảnh báo...) trích từ quy chế, mỗi ngưỡng có trích dẫn."""
    started = time.perf_counter()
    _, agent_id = assign_agent(topic)
    agent = profile(agent_id)
    base = {"agent": agent_id, "agent_name": agent["name"], "evidence": _evidence_meta(evidence), "rules": [],
            "removed": 0, "input_tokens": 0, "output_tokens": 0}
    if not evidence:
        return {**base, "latency_ms": _ms(started)}
    ids = [c.chunk_id for c in evidence]
    system = (
        f"THRESHOLD_EXTRACTOR. Role={agent['name']}. From the EVIDENCE list every numeric condition used to decide the "
        "REVIEW, as label (what is measured, in the document's words), op (>=, >, <=, < or =), value (the number exactly as "
        "written) and unit. Cite the chunk that states it. Only eligibility conditions: skip amounts, benefits and "
        "conditions without a number. Do not invent. applies_to = the group the threshold is for, in the document's words "
        "(e.g. năm thứ nhất, các năm tiếp theo), empty if it applies to everyone. "
        "Write labels in the same language as the REVIEW. " + _language_rule(topic) + " Return JSON only."
    )
    schema = {"type": "object", "properties": {"rules": {"type": "array", "items": {"type": "object", "properties": {
        "label": {"type": "string"}, "op": {"type": "string", "enum": list(OPS)}, "value": {"type": "string"},
        "unit": {"type": "string"}, "applies_to": {"type": "string"}, "citation": {"type": "string", "enum": ids}},
        "required": ["label", "op", "value", "unit", "applies_to", "citation"], "additionalProperties": False}}},
        "required": ["rules"], "additionalProperties": False}
    warning = bool(_WARNING_REVIEW.search(_fold(topic)))
    if warning:  # cảnh báo / buộc thôi học: chỉ lấy điều kiện KÍCH HOẠT ("dưới …", "vượt quá …"), không lấy điều kiện được học tiếp
        system = system.replace(" Return JSON only.", " This REVIEW flags a person when ANY triggering condition holds: list only the "
                                "triggering conditions (e.g. average BELOW a value, failed credits ABOVE a value), never the conditions "
                                "for continuing normally. Return JSON only.")
    response = await _ask(provider, system, f"EVIDENCE:\n{_evidence_block(evidence)}\n\nREVIEW: {topic}", schema)
    by_id = {c.chunk_id: c for c in evidence}
    rules, removed, seen = [], 0, set()
    for raw in _decode(response.text).get("rules") or []:
        if not isinstance(raw, dict):
            continue
        cite, value, op, label = _cited(raw.get("citation"), evidence), _number(raw.get("value")), str(raw.get("op") or ""), _text(raw.get("label"), 160)
        if not (cite and label and value is not None and op in OPS):
            removed += 1
            continue
        if not _value_in(value, by_id[cite].text):
            fix = next((c for c in evidence if _value_in(value, c.text)), None)
            if fix is None:
                removed += 1  # con số không có trong tài liệu: không dùng
                continue
            cite = fix.chunk_id
        y_min, y_max = year_scope(str(raw.get("applies_to") or "") + " " + label)
        key = (label.casefold(), op, value, y_min, y_max)
        if key in seen:
            continue
        seen.add(key)
        rules.append({"label": label, "op": op, "value": value, "unit": _text(raw.get("unit"), 40), "citation": cite,
                      "year_min": y_min, "year_max": y_max, "applies_to": _text(raw.get("applies_to"), 80)})
    if warning:
        rules = warning_rules(rules)
    return {**base, **_usage(response), "rules": rules, "removed": removed, "latency_ms": _ms(started)}


_WARNING_REVIEW = re.compile(r"canh bao|thoi hoc|dinh chi")


def warning_rules(rules: list[dict]) -> list[dict]:
    """Xét cảnh báo (thỏa BẤT KỲ ngưỡng là bị): mô hình hay lẫn điều kiện "được học tiếp" (>= 1,2 năm thứ nhất; nợ <= 16).
    Cùng tiêu chí, cùng giá trị có bản ">= (năm X)" và bản "<" thì gộp thành "< (năm X)"; còn lại bỏ ngưỡng >= / <=
    (trong văn bản pháp quy, điều kiện kích hoạt viết "dưới …", "vượt quá …"). 21/11: trước đó 20/20 sinh viên bị cảnh báo."""
    lows = [r for r in rules if r["op"] in ("<", ">")]
    for hi in (r for r in rules if r["op"] in (">=", "<=") and r.get("year_min")):
        twin = next((r for r in lows if r["label"].casefold() == hi["label"].casefold() and r["value"] == hi["value"]
                     and r["op"] == {">=": "<", "<=": ">"}[hi["op"]]), None)
        if twin is not None and not twin.get("year_min"):
            twin["year_min"], twin["year_max"], twin["applies_to"] = hi["year_min"], hi["year_max"], hi.get("applies_to", "")
        elif twin is None:  # chỉ có bản ">= 1,2 (năm X)": đảo thành "< 1,2 (năm X)"
            lows.append({**hi, "op": {">=": "<", "<=": ">"}[hi["op"]]})
    out, seen = [], set()
    for r in lows:
        key = (r["label"].casefold(), r["op"], r["value"], r.get("year_min"), r.get("year_max"))
        if key not in seen:
            seen.add(key)
            out.append(r)
    # bản "< 1,2" không có năm trùng với bản "< 1,2 (năm thứ nhất)" thì bỏ bản không có năm
    # (so theo phép so sánh + giá trị: mô hình đặt nhãn hai bản hơi khác nhau, vd "ĐTB tích lũy" / "ĐTB tích lũy đạt dưới …")
    scoped = {(r["op"], r["value"]) for r in out if r.get("year_min")}
    return [r for r in out if r.get("year_min") or (r["op"], r["value"]) not in scoped]


def _compare(actual: float, op: str, target: float) -> bool:
    return {">=": actual >= target - 1e-9, ">": actual > target + 1e-9, "<=": actual <= target + 1e-9,
            "<": actual < target - 1e-9, "=": abs(actual - target) < 1e-9}[op]


_YEAR_WORD = {"nhat": 1, "mot": 1, "hai": 2, "ba": 3, "tu": 4, "nam": 5}


def year_scope(text: str) -> tuple[int | None, int | None]:
    """"năm thứ nhất" → (1, 1); "năm thứ 3" → (3, 3); "các năm tiếp theo" / "từ năm thứ tư" → (4, None); không nêu → (None, None).
    Thông tư 08 Điều 11: ngưỡng ĐTB tích lũy khác nhau theo trình độ năm học (21/11: áp cả 4 ngưỡng cho mọi sinh viên là sai)."""
    t = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode().lower()
    if re.search(r"\b(cac nam tiep theo|nam tiep theo|tu nam thu (tu|4) tro (di|len))\b", t):
        return 4, None
    m = re.search(r"\bnam thu (nhat|mot|hai|ba|tu|nam|\d)\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _YEAR_WORD[m.group(1)]
        return n, n
    return None, None


def evaluate_roster(rules: list[dict], columns: list[str], rows: list[list[str]], id_column: int | None = None,
                    mode: str = "all", year_column: int | None = None) -> dict:
    """Xét từng hàng theo các ngưỡng đã gán cột (so bằng mã, không dùng mô hình).
    mode "all" (học bổng, tốt nghiệp): PASS đạt mọi ngưỡng; FAIL trượt ít nhất một; MISSING thiếu số liệu.
    mode "any" (cảnh báo, buộc thôi học): HIT thỏa ít nhất một ngưỡng áp dụng cho hàng đó; CLEAR không thỏa ngưỡng nào; MISSING thiếu số liệu.
    Ngưỡng có year_min/year_max chỉ áp cho hàng có năm học (cột year_column) trong khoảng đó; hàng khác ghi "skip"."""
    for r in rules:
        if r["op"] not in OPS or not (0 <= int(r["column"]) < len(columns)):
            raise ValueError("Ngưỡng có phép so sánh hoặc cột không hợp lệ.")
    if mode not in ("all", "any"):
        raise ValueError("Chế độ xét không hợp lệ.")
    results = []
    for index, row in enumerate(rows):
        year = _number(row[year_column]) if year_column is not None and year_column < len(row) else None
        checks = []
        for r in rules:
            cell = row[int(r["column"])] if int(r["column"]) < len(row) else ""
            lo, hi = r.get("year_min"), r.get("year_max")
            if (lo is not None or hi is not None) and year_column is not None:
                if year is None:
                    checks.append({"label": r["label"], "value": cell, "state": "missing"})
                    continue
                if (lo is not None and year < lo) or (hi is not None and year > hi):
                    checks.append({"label": r["label"], "value": cell, "state": "skip"})
                    continue
            actual = _number(cell)
            state = "missing" if actual is None else ("pass" if _compare(actual, r["op"], float(r["value"])) else "fail")
            checks.append({"label": r["label"], "value": cell, "state": state})
        states = {c["state"] for c in checks}
        if mode == "any":
            status = "HIT" if "pass" in states else "MISSING" if "missing" in states else "CLEAR"
        else:
            status = "FAIL" if "fail" in states else "MISSING" if "missing" in states else "PASS"
        name = row[id_column] if id_column is not None and id_column < len(row) else f"Hàng {index + 2}"
        results.append({"row": index, "name": name, "status": status, "checks": checks})
    keys = ("HIT", "CLEAR", "MISSING") if mode == "any" else ("PASS", "FAIL", "MISSING")
    count = {k: sum(1 for x in results if x["status"] == k) for k in keys}
    return {"mode": mode, "results": results, "summary": {"total": len(results), **count}}


# ------------------------------------------------------------------ sinh câu hỏi ôn tập (Giáo dục) / hỏi đáp chính sách (Nhân sự)
def spread_chunks(chunks: list[SourceChunk], limit: int = 6) -> list[SourceChunk]:
    """Lấy đều các đoạn trong tài liệu (đầu, giữa, cuối) thay vì chỉ vài đoạn đầu."""
    ordered = sorted(chunks, key=lambda c: (c.source_id, c.index))
    if len(ordered) <= limit:
        return ordered
    step = len(ordered) / limit
    return [ordered[int(i * step)] for i in range(limit)]


BATCH = 5  # mỗi lượt tối đa 5 mục để JSON không bị cắt ở giới hạn độ dài của mô hình


def _language_rule(text: str) -> str:
    from app.research.pipeline import reply_language_of  # nhập muộn tránh vòng import
    return "Write every field in Vietnamese." if reply_language_of(text) == "vi" else "Write every field in English."


def _check_item(kind: str, raw: object, evidence: list[SourceChunk], by_id: dict) -> dict | None:
    """Mục hợp lệ hoặc None: có trích dẫn; quiz đủ 4 phương án khác nhau và đáp án đúng nằm trong đoạn trích;
    faq không thêm con số không có trong đoạn trích."""
    if not isinstance(raw, dict):
        return None
    cite, question = _cited(raw.get("citation"), evidence), _text(raw.get("question"), 400)
    if not cite or not question:
        return None
    source = by_id[cite].text
    if kind == "quiz":
        options = [_text(o, 200) for o in raw.get("options") or []] if isinstance(raw.get("options"), list) else []
        answer = raw.get("answer")
        if not (len(options) == 4 and all(options) and len({o.casefold() for o in options}) == 4 and isinstance(answer, int) and 0 <= answer < 4):
            return None
        if _coverage(options[answer], source) < 0.6 or _numbers(_rule_text(options[answer])) - _numbers(_rule_text(source)):
            return None  # đáp án không nằm trong đoạn trích: câu đoán
        return {"question": question, "options": options, "answer": answer, "explanation": _text(raw.get("explanation"), 400), "citation": cite}
    answer_text = _text(raw.get("answer"), 800)
    # 21/11: chỉ so với đúng đoạn được trích thì bỏ gần hết câu (mô hình hay dẫn đoạn bên cạnh, hay ghi "(Điều 6)");
    # so với mọi đoạn đã đưa cho mô hình, không tính số Điều. Câu có con số ngoài các đoạn đó vẫn bị bỏ.
    allowed = _numbers(_rule_text(" ".join(c.text for c in evidence)))
    if not answer_text or _numbers(_rule_text(re.sub(r"Điều\s+\d+(?:\.\d+)?", " ", answer_text))) - allowed:
        return None
    return {"question": question, "answer": answer_text, "citation": cite}


def _topic_aligned(item: dict, source_text: str, topic: str) -> bool:
    """Kiểm tra mục quiz/faq có bám từ khóa chủ đề người dùng yêu cầu hay lệch chủ đề."""
    t_words = [w for w in re.findall(r"\w+", _rule_text(topic)) if len(w) >= 3 and w not in {"tạo", "câu", "hỏi", "trắc", "nghiệm", "về", "theo", "và", "các", "của"}]
    if not t_words:
        return True
    hay = _rule_text(f"{item.get('question', '')} {item.get('explanation', '')} {item.get('answer', '')} {source_text}")
    hits = sum(1 for w in set(t_words) if w in hay)
    return hits >= min(2, max(1, len(set(t_words))))


async def generate_items(provider, kind: str, chunks: list[SourceChunk], count: int, *, topic: str | None = None) -> dict:
    """quiz: trắc nghiệm 4 phương án có đáp án; faq: câu hỏi thường gặp kèm câu trả lời. Mỗi mục có trích dẫn.
    Sinh theo lượt (tối đa 5 mục/lượt, mỗi lượt một nhóm đoạn khác nhau), bỏ câu trùng giữa các lượt."""
    started = time.perf_counter()
    count = max(1, min(int(count), 15))
    clean_topic = (topic or "").strip()
    evidence = spread_chunks(chunks)
    _, agent_id = assign_agent(" ".join(c.text[:300] for c in evidence))
    agent = profile(agent_id)
    base = {"kind": kind, "agent": agent_id, "agent_name": agent["name"], "evidence": _evidence_meta(evidence), "items": [],
            "removed": 0, "input_tokens": 0, "output_tokens": 0}
    if not evidence:
        return {**base, "latency_ms": _ms(started)}
    language = _language_rule(" ".join(c.text[:400] for c in evidence))
    by_id = {c.chunk_id: c for c in evidence}
    batches = math.ceil(count / BATCH)
    items: list[dict] = []
    removed, usage = 0, {"input_tokens": 0, "output_tokens": 0}
    topic_rule = f" TOPIC REQUIREMENT: every item MUST directly test \"{clean_topic}\"; ignore unrelated sections/articles." if clean_topic else ""
    for b in range(batches):
        need = min(BATCH, count - len(items))
        if need <= 0:
            break
        part = evidence[b::batches] or evidence
        ids = [c.chunk_id for c in part]
        asked = "; ".join(i["question"] for i in items)
        if kind == "quiz":
            system = (f"QUIZ_WRITER. Role={agent['name']}. Write {need} multiple-choice review questions answerable ONLY from "
                      "the EVIDENCE. Each has exactly 4 different short options, answer = index 0-3 of the correct option, an "
                      f"explanation of at most 25 words, and the cited chunk.{topic_rule} {language} Return JSON only.")
            item = {"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "integer"}, "explanation": {"type": "string"}, "citation": {"type": "string", "enum": ids}}
        else:
            system = (f"FAQ_WRITER. Role={agent['name']}. Write {need} questions employees would really ask that the EVIDENCE "
                      "answers, each answered in at most 40 words with its numbers and conditions, citing the chunk."
                      f"{topic_rule} {language} Return JSON only.")
            item = {"question": {"type": "string"}, "answer": {"type": "string"}, "citation": {"type": "string", "enum": ids}}
        schema = {"type": "object", "properties": {"items": {"type": "array", "items": {
            "type": "object", "properties": item, "required": list(item), "additionalProperties": False}}},
            "required": ["items"], "additionalProperties": False}
        user = (f"REQUESTED TOPIC: {clean_topic}\n\n" if clean_topic else "") + f"EVIDENCE:\n{_evidence_block(part)}" + (f"\n\nALREADY ASKED (do not repeat): {asked}" if asked else "")
        response = await _ask(provider, system, user, schema, max_tokens=1600)
        for k, v in _usage(response).items():
            usage[k] += v
        seen = {i["question"].casefold() for i in items}
        for raw in _decode(response.text).get("items") or []:
            entry = _check_item(kind, raw, part, by_id)
            if entry is None:
                removed += 1
            elif entry["question"].casefold() not in seen and len(items) < count:
                seen.add(entry["question"].casefold())
                items.append(entry)
    mismatch = 0
    if clean_topic and items:
        q_only_words = [w for w in re.findall(r"\w+", _rule_text(clean_topic)) if len(w) >= 3 and w not in {"tạo", "câu", "hỏi", "trắc", "nghiệm", "về", "theo", "và", "các", "của"}]
        if q_only_words:
            on_topic: list[dict] = []
            for it in items:
                it_txt = _rule_text(f"{it.get('question', '')} {it.get('explanation', '')} {it.get('answer', '')}")
                if any(w in it_txt for w in q_only_words):
                    on_topic.append(it)
                else:
                    mismatch += 1
            items = on_topic
    out = {**base, **usage, "items": items, "removed": removed + mismatch, "requested_count": count,
           "returned_count": len(items), "latency_ms": _ms(started)}
    if mismatch:
        out["topic_mismatch_count"] = mismatch
        out["off_topic_removed"] = mismatch
        out["topic_warning"] = f"Đã loại {mismatch} mục lệch chủ đề yêu cầu ({clean_topic}); còn {len(items)}/{count} mục."
    elif len(items) < count:
        out["topic_warning"] = f"Chỉ tạo được {len(items)}/{count} mục đạt chuẩn từ tài liệu."
    return out


# ------------------------------------------------------------------ tra cứu quy chế theo Điều (Giáo dục)
_ARTICLE = re.compile(r"^\s*#{0,6}\s*\**\s*Điều\s+(\d+[a-zđ]?)\s*[.:\-–]?\s*(.*?)\**\s*$", re.IGNORECASE)
_CHAPTER = re.compile(r"^\s*#{0,6}\s*\**\s*(Chương\s+[IVXLC\d]+.*?)\**\s*$", re.IGNORECASE)


def split_articles(source_name: str, text: str) -> list[dict]:
    """Cắt văn bản theo "Điều N"; mỗi Điều giữ chương chứa nó. Không có Điều nào thì trả rỗng."""
    articles: list[dict] = []
    chapter = ""
    for line in text.splitlines():
        if (m := _CHAPTER.match(line)) and not _ARTICLE.match(line):
            chapter = m.group(1).strip()
            continue
        if m := _ARTICLE.match(line):
            articles.append({"number": m.group(1), "title": m.group(2).strip(" *#"), "chapter": chapter,
                             "source_name": source_name, "lines": []})
        elif articles and line.strip():
            articles[-1]["lines"].append(line.strip())
    return [{**{k: v for k, v in a.items() if k != "lines"}, "text": "\n".join(a["lines"])} for a in articles]


async def lookup_articles(provider, question: str, articles: list[dict], top_k: int = 3) -> dict:
    """Xếp hạng Điều theo câu hỏi (BM25), mô hình trả lời chỉ từ các Điều đó; Điều được dẫn phải nằm trong danh sách."""
    started = time.perf_counter()
    pseudo = [SourceChunk(f"a{i}", a["source_name"], a["source_name"], f"Điều {a['number']}. {a['title']}\n{a['text']}", i)
              for i, a in enumerate(articles)]
    ranked = bm25_rank(question, pseudo)[:top_k]
    picked = [articles[int(c.chunk_id[1:])] for c in ranked]
    _, agent_id = assign_agent(question)
    agent = profile(agent_id)
    base = {"agent": agent_id, "agent_name": agent["name"], "articles": picked, "answer": "", "cited": [], "flags": [],
            "input_tokens": 0, "output_tokens": 0}
    if not picked:
        return {**base, "flags": ["no_article"], "latency_ms": _ms(started)}
    # mã A1, A2… thay cho số Điều: hai văn bản cùng có "Điều 10" vẫn phân biệt được
    refs = {f"A{i + 1}": a for i, a in enumerate(picked)}
    block = "\n\n".join(f"[{r}] ({a['source_name']}) Điều {a['number']}. {a['title']}\n{a['text']}" for r, a in refs.items())
    system = (f"REGULATION_LOOKUP. Role={agent['name']}. Answer the QUESTION only from the ARTICLES, briefly, and list the "
              "codes (A1, A2…) of the articles you used. If the articles do not answer it, say so. " + _language_rule(question) + " Return JSON only.")
    schema = {"type": "object", "properties": {"answer": {"type": "string"},
              "articles": {"type": "array", "items": {"type": "string", "enum": list(refs)}}},
              "required": ["answer", "articles"], "additionalProperties": False}
    response = await _ask(provider, system, f"ARTICLES:\n{block}\n\nQUESTION: {question}", schema)
    obj = _decode(response.text)
    used_refs = [r for r in dict.fromkeys(str(x) for x in obj.get("articles") or []) if r in refs]
    cited = [f"{refs[r]['source_name']}#{refs[r]['number']}" for r in used_refs]  # khóa "tên tệp#số Điều"
    answer, flags = _text(obj.get("answer"), 1200), []
    used = " ".join(refs[r]["text"] for r in used_refs) or block
    if not cited:
        flags.append("no_article_cited")
    if _numbers(_rule_text(answer)) - _numbers(_rule_text(used)):
        flags.append("numbers_not_in_articles")  # câu trả lời có con số không có trong Điều được dẫn
    return {**base, **_usage(response), "answer": answer, "cited": cited, "flags": flags, "latency_ms": _ms(started)}


# ------------------------------------------------------------------ Nhân sự: hệ số phép năm, làm thêm giờ + tính toán
PAY_FIELDS = {
    "leave_base_days": "Số ngày phép năm khi làm đủ 12 tháng",
    "leave_extra_days": "Số ngày phép cộng thêm theo thâm niên",
    "leave_every_years": "Cứ đủ bao nhiêu năm làm việc thì được cộng thêm",
    "ot_weekday_pct": "Tỷ lệ tiền làm thêm ngày thường (% lương giờ)",
    "ot_rest_pct": "Tỷ lệ tiền làm thêm ngày nghỉ hằng tuần (% lương giờ)",
    "ot_holiday_pct": "Tỷ lệ tiền làm thêm ngày lễ (% lương giờ)",
    "ot_month_cap": "Số giờ làm thêm tối đa mỗi tháng",
}


async def extract_pay_rates(provider, evidence: list[SourceChunk]) -> dict:
    started = time.perf_counter()
    _, agent_id = assign_agent("nghỉ phép làm thêm giờ lương")
    agent = profile(agent_id)
    base = {"agent": agent_id, "agent_name": agent["name"], "evidence": _evidence_meta(evidence),
            "rates": {k: None for k in PAY_FIELDS}, "input_tokens": 0, "output_tokens": 0}
    if not evidence:
        return {**base, "latency_ms": _ms(started)}
    ids = [c.chunk_id for c in evidence]
    fields = "\n".join(f"- {k}: {v}" for k, v in PAY_FIELDS.items())
    system = (f"PAY_RULE_EXTRACTOR. Role={agent['name']}. For each FIELD give the number stated in the EVIDENCE and cite the "
              "chunk; use an empty value when the evidence does not state it. Do not compute or guess. Return JSON only.")
    schema = {"type": "object", "properties": {"fields": {"type": "array", "items": {"type": "object", "properties": {
        "key": {"type": "string", "enum": list(PAY_FIELDS)}, "value": {"type": "string"}, "citation": {"type": "string", "enum": ids}},
        "required": ["key", "value", "citation"], "additionalProperties": False}}}, "required": ["fields"], "additionalProperties": False}
    response = await _ask(provider, system, f"EVIDENCE:\n{_evidence_block(evidence)}\n\nFIELDS:\n{fields}", schema)
    by_id = {c.chunk_id: c for c in evidence}
    rates: dict[str, dict | None] = {k: None for k in PAY_FIELDS}
    for raw in _decode(response.text).get("fields") or []:
        if not isinstance(raw, dict) or raw.get("key") not in PAY_FIELDS or rates[raw["key"]] is not None:
            continue
        cite, value = _cited(raw.get("citation"), evidence), _number(raw.get("value"))
        if cite and value is not None and value >= 0:
            if not _value_in(value, by_id[cite].text):
                fix = next((c for c in evidence if _value_in(value, c.text)), None)
                cite = fix.chunk_id if fix else None
            if cite:
                rates[raw["key"]] = {"value": value, "citation": cite}
    return {**base, **_usage(response), "rates": rates, "latency_ms": _ms(started)}


def compute_pay(rates: dict[str, float | None], employees: list[dict]) -> dict:
    """Tính bằng mã cố định. Phép năm: dưới 12 tháng tính theo tỷ lệ tháng (làm tròn xuống); từ 12 tháng = cơ bản +
    cộng thêm theo thâm niên. Tiền làm thêm = lương giờ x giờ x tỷ lệ. Thiếu hệ số thì để trống, không giả định."""
    def rate(key):
        v = rates.get(key)
        return None if v is None else float(v)

    base, extra, every = rate("leave_base_days"), rate("leave_extra_days"), rate("leave_every_years")
    pct = {"weekday": rate("ot_weekday_pct"), "rest": rate("ot_rest_pct"), "holiday": rate("ot_holiday_pct")}
    cap = rate("ot_month_cap")
    out = []
    for e in employees:
        months = _number(e.get("months"))
        hourly = _number(e.get("hourly"))
        hours = {k: _number(e.get(f"{k}_hours")) or 0.0 for k in pct}
        used = _number(e.get("used_days")) or 0.0
        notes = []
        leave = None
        if base is not None and months is not None and months >= 0:
            if months < 12:
                leave = math.floor(base * months / 12)
            else:
                leave = base
                if extra is not None and every:
                    leave += extra * math.floor((months / 12) / every)
                elif extra is not None:
                    notes.append("Thiếu số năm để được cộng thêm ngày phép.")
        elif base is None:
            notes.append("Chưa có số ngày phép năm từ nội quy.")
        else:
            notes.append("Thiếu số tháng làm việc để tính phép năm.")
        overtime = None
        if any(hours.values()):
            if hourly is None:
                notes.append("Thiếu lương giờ để tính tiền làm thêm.")
            elif any(pct[k] is None and hours[k] for k in pct):
                notes.append("Thiếu tỷ lệ làm thêm cho loại ngày có giờ làm thêm.")
            else:
                overtime = round(sum(hourly * hours[k] * (pct[k] or 0) / 100 for k in pct))
        total_hours = sum(hours.values())
        if cap is not None and total_hours > cap:
            notes.append(f"Tổng {_fmt(total_hours)} giờ làm thêm vượt mức tối đa {_fmt(cap)} giờ/tháng.")
        out.append({"name": _text(e.get("name"), 120) or "Nhân viên", "leave_days": leave,
                    "leave_left": None if leave is None else leave - used, "overtime_pay": overtime,
                    "overtime_hours": total_hours, "notes": notes})
    return {"employees": out}


# ------------------------------------------------------------------ Nhân sự: cấp duyệt đơn từ
_DAYS = re.compile(r"(\d+(?:[.,]\d+)?)\s*ngày", re.I)
# "từ N ngày trở lên do X duyệt" / "Nghỉ từ N ngày trở lên: X duyệt" / "từ N ngày liên tiếp trở lên phải được X phê duyệt"
# (thử theo vai 20/11: dạng có dấu hai chấm không được nhận, đơn 4 ngày bị trả về Trưởng phòng thay vì Giám đốc)
_SEP = r"(?::|\b(?:do|bởi)\b|\bphải\s+được\b)"
_LEVEL_HI = re.compile(r"từ\s+(\d+)\s+ngày(?:\s+liên\s+tiếp)?\s+trở\s+lên[^;.\n]*?" + _SEP + r"\s*([^;.,:\n]+?)\s+(?:phê\s+)?duyệt", re.I)
_LEVEL_LO = re.compile(r"dưới\s+(\d+)\s+ngày[^;.\n]*?" + _SEP + r"\s*([^;.,:\n]+?)\s+(?:phê\s+)?duyệt", re.I)


def approver_by_days(request: str, text: str) -> str | None:
    """Ngưỡng ngày trong quy định ("từ N ngày trở lên do X duyệt; dưới N ngày do Y duyệt") so với số ngày của đơn.

    Phép so sánh do luật cố định làm (chạy thật 19/11: mô hình chọn Trưởng phòng cho đơn 6 ngày dù ngưỡng là 5).
    Không đủ dữ kiện (đơn không nêu số ngày, quy định không có ngưỡng) thì trả None để giữ câu trả lời có căn cứ của mô hình.
    """
    asked = _DAYS.search(request)
    hi = _LEVEL_HI.search(text)
    if not asked or not hi:
        return None
    days = float(asked.group(1).replace(",", "."))
    if days >= int(hi.group(1)):
        return hi.group(2).strip()
    lo = _LEVEL_LO.search(text)
    return lo.group(2).strip() if lo and int(lo.group(1)) == int(hi.group(1)) else None


async def find_approver(provider, request: str, evidence: list[SourceChunk]) -> dict:
    """Ai duyệt loại đơn này theo nội quy (kèm ngưỡng nếu có). Tên người/đơn vị duyệt phải có trong đoạn được dẫn."""
    started = time.perf_counter()
    _, agent_id = assign_agent(request)
    agent = profile(agent_id)
    base = {"agent": agent_id, "agent_name": agent["name"], "approver": "", "rule": "", "citation": None, "input_tokens": 0, "output_tokens": 0}
    if not evidence:
        return {**base, "latency_ms": _ms(started)}
    ids = [c.chunk_id for c in evidence]
    system = (f"APPROVER_FINDER. Role={agent['name']}. From the EVIDENCE find who must approve the REQUEST (person or "
              "unit, exactly as written) and quote the rule that decides it, including thresholds. Cite the chunk. If the "
              "evidence does not say, leave approver empty. " + _language_rule(request) + " Return JSON only.")
    schema = {"type": "object", "properties": {"approver": {"type": "string"}, "rule": {"type": "string"},
              "citation": {"type": "string", "enum": ids}}, "required": ["approver", "rule", "citation"], "additionalProperties": False}
    user = f"EVIDENCE:\n{_evidence_block(evidence)}\n\nREQUEST: {request}"
    response = await _ask(provider, system, user, schema)
    obj = _decode(response.text)
    usage = _usage(response)
    if not _text(obj.get("approver")):
        # mô hình nhỏ hay trả rỗng dù nội quy có phân cấp duyệt: hỏi lại một lần, nhắc chọn mức khớp với đơn
        response = await _ask(provider, system, user + "\n\nThe EVIDENCE may set approval levels by number of days or "
                              "amount; pick the level that matches the REQUEST and copy the approver as written.", schema)
        obj = _decode(response.text)
        usage = {k: usage[k] + v for k, v in _usage(response).items()}
    cite, approver, rule = _cited(obj.get("citation"), evidence), _text(obj.get("approver"), 160), _text(obj.get("rule"), 400)
    by_id = {c.chunk_id: c for c in evidence}
    for c in ([by_id[cite]] if cite else []) + [c for c in evidence if c.chunk_id != cite]:
        ruled = approver_by_days(request, c.text)
        if ruled:  # quy định có ngưỡng ngày và đơn nêu số ngày: kết luận theo phép so sánh, dẫn đúng đoạn chứa ngưỡng
            if _fold(ruled) != _fold(approver):
                rule = (rule + " " if rule else "") + "(Cấp duyệt xác định theo ngưỡng số ngày trong quy định.)"
            cite, approver = c.chunk_id, ruled
            break
    if not (cite and approver and _fold(approver) in _fold(by_id[cite].text)):  # nguyên cụm, không chỉ trùng vài chữ
        return {**base, **usage, "latency_ms": _ms(started)}  # không có căn cứ: không nêu người duyệt
    return {**base, **usage, "approver": approver, "rule": rule, "citation": cite, "latency_ms": _ms(started)}


# ------------------------------------------------------------------ Pháp lý: rà soát hợp đồng
# Điều 398 Bộ luật Dân sự 2015 (Nội dung của hợp đồng): các bên có thể thỏa thuận các nội dung sau.
CONTRACT_CRITERIA = [
    ("BLDS398-a", "Đối tượng của hợp đồng", "Điều 398 BLDS 2015"),
    ("BLDS398-b", "Số lượng, chất lượng", "Điều 398 BLDS 2015"),
    ("BLDS398-c", "Giá, phương thức thanh toán", "Điều 398 BLDS 2015"),
    ("BLDS398-d", "Thời hạn, địa điểm, phương thức thực hiện hợp đồng", "Điều 398 BLDS 2015"),
    ("BLDS398-dd", "Quyền, nghĩa vụ của các bên", "Điều 398 BLDS 2015"),
    ("BLDS398-e", "Trách nhiệm do vi phạm hợp đồng", "Điều 398 BLDS 2015"),
    ("BLDS398-g", "Phương thức giải quyết tranh chấp", "Điều 398 BLDS 2015"),
    ("HD-TH1", "Thông tin các bên (tên, địa chỉ, người đại diện)", "Thực hành soạn thảo"),
    ("HD-TH2", "Thời điểm có hiệu lực và chữ ký của các bên", "Thực hành soạn thảo"),
]
CONTRACT_TERMS = {
    "BLDS398-a": ["đối tượng", "cung cấp", "mua bán", "dịch vụ", "hàng hóa", "công việc"],
    "BLDS398-b": ["số lượng", "chất lượng", "tiêu chuẩn", "quy cách", "bảo đảm"],
    "BLDS398-c": ["giá", "thanh toán"],
    "BLDS398-d": ["thời hạn", "thời gian", "địa điểm", "từ ngày"],
    "BLDS398-dd": ["quyền", "nghĩa vụ"],
    "BLDS398-e": ["vi phạm", "phạt", "bồi thường"],
    "BLDS398-g": ["tranh chấp", "hòa giải", "hoà giải", "trọng tài", "tòa án", "toà án", "thương lượng"],
    "HD-TH1": ["bên a", "bên b", "đại diện"],
    "HD-TH2": ["hiệu lực", "ký"],
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.casefold())
    return re.sub(r"\s+", " ", "".join(c for c in text if unicodedata.category(c) != "Mn").replace("đ", "d")).strip()


# Luật kiểm cố định (21/11): mô hình 4B bỏ sót các rủi ro điển hình nhất (phạt 30%, giới hạn bồi thường kể cả cố ý,
# dùng dữ liệu để huấn luyện AI, tự gia hạn…). Mỗi luật: (mẫu trên câu đã bỏ dấu, mức, lý do, hàm kiểm thêm hoặc None).
def _penalty_over_8(sentence: str) -> bool:
    return any(float(x.replace(",", ".")) > 8 for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", sentence))


CONTRACT_RULES = [
    (r"\bphat\b", "HIGH", "Mức phạt vi phạm trên 8%: Luật Thương mại 2005 (Điều 301) giới hạn mức phạt không quá 8% giá trị phần nghĩa vụ bị vi phạm.", _penalty_over_8),
    (r"(khong vuot qua|toi da).{0,80}(ke ca|ca khi).{0,40}co y", "HIGH", "Giới hạn hoặc miễn trách nhiệm bồi thường kể cả khi có lỗi cố ý: điều khoản như vậy rất bất lợi và dễ bị coi là không có hiệu lực; cần đàm phán lại.", None),
    (r"(huan luyen|dao tao).{0,60}(mo hinh|tri tue nhan tao|\bai\b)|(mo hinh|tri tue nhan tao).{0,60}(huan luyen)", "HIGH", "Bên kia được dùng dữ liệu (có thể gồm dữ liệu cá nhân) để huấn luyện AI: cần sự đồng ý của chủ thể dữ liệu theo Nghị định 13/2023; nên cấm hoặc giới hạn rõ.", None),
    (r"tu dong gia han", "MEDIUM", "Tự động gia hạn: dễ bị ràng buộc thêm nhiều năm nếu quên thông báo; kiểm tra thời hạn báo trước và đơn giá khi gia hạn.", None),
    (r"(khong (can|phai) (thong bao|bao truoc)|khong duoc phan doi|theo chinh sach gia cua ben)", "HIGH", "Một bên được tự thay đổi giá hoặc phạm vi mà bên kia không được phản đối hoặc không cần báo trước.", None),
    (r"(don phuong cham dut).{0,80}(bat ky luc nao|khong phai boi thuong)", "HIGH", "Quyền đơn phương chấm dứt không cần lý do, không bồi thường, chỉ dành cho một bên.", None),
    (r"(trong tai|toa an).{0,60}(singapore|siac|nuoc ngoai|quoc te)|ngon ngu trong tai la tieng anh", "MEDIUM", "Giải quyết tranh chấp ở nước ngoài, bằng tiếng nước ngoài: chi phí và rủi ro tố tụng cao cho bên Việt Nam.", None),
    (r"luu giu du lieu.{0,60}\d+\s*nam|tu quyet dinh viec xoa", "MEDIUM", "Bên kia giữ dữ liệu lâu sau khi chấm dứt hợp đồng hoặc tự quyết việc xóa: trái nguyên tắc xóa dữ liệu khi hết mục đích.", None),
    (r"khong duoc thue ben thu ba kiem tra bao mat|kiem thu xam nhap", "LOW", "Hạn chế quyền tự kiểm tra bảo mật hệ thống đang lưu dữ liệu của mình.", None),
    (r"lai cham tra\s*\d+(?:[.,]\d+)?\s*%\s*/\s*ngay", "MEDIUM", "Lãi chậm trả tính theo ngày ở mức cao (0,5%/ngày ≈ 180%/năm): cần đối chiếu mức lãi pháp luật cho phép.", None),
]


def _sentences(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.;])\s+|\n+", text or "") if len(x.strip()) >= 12]


def rule_risks(evidence: list[SourceChunk]) -> list[dict]:
    """Rủi ro bắt bằng luật cố định, trích nguyên văn đúng câu trong hợp đồng (không gọi mô hình)."""
    out, seen = [], set()
    for c in evidence:
        for sent in _sentences(c.text):
            folded = _fold(sent)
            for pattern, level, reason, extra in CONTRACT_RULES:
                if re.search(pattern, folded) and (extra is None or extra(sent)) and (pattern, sent) not in seen:
                    seen.add((pattern, sent))
                    out.append({"quote": sent[:500], "level": level, "reason": reason + " (luật kiểm cố định)", "citation": c.chunk_id, "rule": True})
    return out


async def contract_risks(provider, evidence: list[SourceChunk]) -> dict:
    """Điều khoản bất lợi hoặc rủi ro; trích nguyên văn phải có trong đoạn được dẫn, nếu không thì bỏ."""
    started = time.perf_counter()
    _, agent_id = assign_agent("hợp đồng")
    agent = profile(agent_id)
    base = {"agent": agent_id, "agent_name": agent["name"], "evidence": _evidence_meta(evidence), "risks": [], "removed": 0,
            "input_tokens": 0, "output_tokens": 0}
    if not evidence:
        return {**base, "latency_ms": _ms(started)}
    ids = [c.chunk_id for c in evidence]
    system = (f"CONTRACT_RISK_REVIEWER. Role={agent['name']}. Find clauses in the CONTRACT that are one-sided, vague, or risky "
              "(unilateral termination or change, unlimited liability, very high penalties, automatic renewal, unclear "
              "deadlines or amounts). For each give the exact quote copied from the contract, the risk level (HIGH, MEDIUM "
              "or LOW), a short reason and the cited chunk. Do not invent clauses. " + _language_rule(" ".join(c.text[:400] for c in evidence)) + " Return JSON only.")
    schema = {"type": "object", "properties": {"risks": {"type": "array", "items": {"type": "object", "properties": {
        "quote": {"type": "string"}, "level": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "reason": {"type": "string"}, "citation": {"type": "string", "enum": ids}},
        "required": ["quote", "level", "reason", "citation"], "additionalProperties": False}}},
        "required": ["risks"], "additionalProperties": False}
    response = await _ask(provider, system, f"CONTRACT:\n{_evidence_block(evidence)}", schema)
    by_id = {c.chunk_id: c for c in evidence}
    risks, removed = [], 0
    for raw in _decode(response.text).get("risks") or []:
        if not isinstance(raw, dict):
            continue
        cite, quote = _cited(raw.get("citation"), evidence), _text(raw.get("quote"), 500)
        level = str(raw.get("level") or "").upper()
        if cite and quote and len(quote) >= 8 and _fold(quote) not in _fold(by_id[cite].text):
            fix = next((c for c in evidence if _fold(quote) in _fold(c.text)), None)
            cite = fix.chunk_id if fix else None
        if not (cite and quote and len(quote) >= 8 and level in ("HIGH", "MEDIUM", "LOW")):
            removed += 1  # trích dẫn không có nguyên văn trong hợp đồng
            continue
        risks.append({"quote": quote, "level": level, "reason": _text(raw.get("reason"), 400), "citation": cite})
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    # gộp luật cố định: câu mô hình đã nêu thì nâng mức và ghi thêm lý do của luật; câu mô hình bỏ sót thì thêm vào
    for rr in rule_risks(evidence):
        same = next((r for r in risks if _fold(r["quote"])[:60] in _fold(rr["quote"]) or _fold(rr["quote"])[:60] in _fold(r["quote"])), None)
        if same is None:
            risks.append(rr)
        elif order[rr["level"]] < order[same["level"]]:  # luật chấm nặng hơn mô hình: lấy mức và lý do của luật (không nối hai lý do trái nhau)
            same["level"], same["reason"] = rr["level"], rr["reason"]
        elif rr["reason"] not in same["reason"]:
            same["reason"] = (same["reason"] + " " if same["reason"] else "") + rr["reason"]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return {**base, **_usage(response), "risks": sorted(risks, key=lambda r: order[r["level"]]), "removed": removed, "latency_ms": _ms(started)}


# ------------------------------------------------------------------ Pháp lý: hiệu lực văn bản (không dùng mô hình)
_DOC_NO = re.compile(r"\b(\d{1,4}/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*)\b")
_DOC_KIND = re.compile(r"\b(Luật|Bộ luật|Nghị định|Thông tư liên tịch|Thông tư|Quyết định|Nghị quyết|Chỉ thị|Công văn)\b", re.IGNORECASE)
_VN_DATE = r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})"
_EFFECTIVE = re.compile(r"có hiệu lực(?: thi hành)?(?: kể)?\s*từ\s*" + _VN_DATE, re.IGNORECASE)
_REPLACES = re.compile(r"(?:thay thế|bãi bỏ|hết hiệu lực|sửa đổi|bổ sung)[^.\n]{0,160}", re.IGNORECASE)
# "bãi bỏ Điều 5 của …", "sửa đổi khoản 2 …": chỉ một phần văn bản, văn bản đó vẫn còn hiệu lực
_PARTIAL = re.compile(r"(?:sửa đổi|bổ sung|\b(?:điều|khoản|điểm|chương|mục)\s+(?:\d+[a-zđ]?|[a-zđ])(?!\w))", re.IGNORECASE)
_OWN_NO = re.compile(r"Số\s*[:.]?\s*(\d{1,4}/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*)")
# "Luật … số 51/2005/QH11 hết hiệu lực kể từ …" (số hiệu đứng TRƯỚC chữ "hết hiệu lực"; 21/11: Luật GDĐT 2023 Điều 52)
_EXPIRES_AFTER = re.compile(r"(\d{1,4}/\d{4}/[A-ZĐ][A-ZĐ0-9\-]*)[^.;]{0,60}?\bhết hiệu lực\b", re.IGNORECASE)


def _date(m: re.Match | None) -> date | None:
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def document_validity(docs: list[tuple[str, str, str]], today: date | None = None) -> dict:
    """docs: (source_id, tên tệp, nội dung). Số hiệu lấy ở 1.500 ký tự đầu; ngày hiệu lực từ câu "có hiệu lực từ ngày";
    văn bản bị thay thế khi một văn bản khác trong kho nêu "thay thế/bãi bỏ ... <số hiệu>"."""
    today = today or date.today()
    items = []
    for source_id, name, text in docs:
        head = text[:1500]
        own = _OWN_NO.search(head) or _DOC_NO.search(head)  # ưu tiên dòng "Số: …", không lấy số văn bản được viện dẫn
        kind_match = _DOC_KIND.search(head)
        number = own.group(1) if own else None
        kind = kind_match.group(1).capitalize() if kind_match else ""
        effective = _date(_EFFECTIVE.search(text))
        issued = _date(re.search(_VN_DATE, head, re.IGNORECASE))
        replaces, amends = set(), set()
        flat = re.sub(r"\s+", " ", text)  # số hiệu hay bị ngắt sang dòng riêng
        for n in _EXPIRES_AFTER.findall(flat):
            if n != number:
                replaces.add(n)
        for clause in _REPLACES.findall(flat):
            for n in _DOC_NO.findall(clause):
                if n == number:
                    continue
                before = clause[:clause.find(n)]
                (amends if _PARTIAL.search(before) else replaces).add(n)
        refs = sorted({n for n in _DOC_NO.findall(text) if n != number} - replaces - amends)
        items.append({"source_id": source_id, "source_name": name, "number": number, "kind": kind,
                      "issued": issued.isoformat() if issued else None, "effective": effective.isoformat() if effective else None,
                      "replaces": sorted(replaces), "amends": sorted(amends - replaces), "references": refs[:20]})

    def label(it: dict) -> str:
        return it["number"] or it["source_name"]

    def in_force(it: dict) -> bool | None:
        return None if not it["effective"] else date.fromisoformat(it["effective"]) <= today

    for it in items:
        replacers = [o for o in items if it["number"] and it["number"] in o["replaces"]]
        amenders = [o for o in items if it["number"] and it["number"] in o["amends"]]
        active = [o for o in replacers if in_force(o) is not False]  # văn bản thay thế chưa đến ngày hiệu lực thì chưa thay được
        pending = [o for o in replacers if in_force(o) is False]
        notes = []
        if active:
            it["status"] = "REPLACED"
            notes.append(f"Bị thay thế/bãi bỏ bởi {', '.join(label(o) for o in active)}"
                         + (" (văn bản đó không nêu ngày hiệu lực)" if any(in_force(o) is None for o in active) else ""))
        elif it["effective"] and in_force(it) is False:
            it["status"] = "NOT_YET"
            notes.append(f"Có hiệu lực từ {it['effective']}")
        elif it["effective"]:
            it["status"] = "IN_FORCE"
            notes.append("Đã có hiệu lực")
        else:
            it["status"] = "UNKNOWN"
            notes.append("Không tìm thấy câu nêu ngày có hiệu lực")
        notes += [f"Sẽ bị thay thế bởi {label(o)} từ {o['effective']}" for o in pending]
        notes += [f"Bị sửa đổi/bãi bỏ một phần bởi {label(o)}" for o in amenders]
        it["status_note"] = "; ".join(notes)
    return {"today": today.isoformat(), "documents": items}
