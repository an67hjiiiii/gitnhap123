"""Hồ sơ tài liệu: tóm tắt, thuật ngữ, câu hỏi gợi ý, tài liệu liên quan, chất lượng, thông tin nhạy cảm, so sánh phiên bản.

Phần chạy tại máy (chất lượng, thông tin nhạy cảm, liên quan, so sánh) không gọi mô hình. Phần cần mô hình (tóm tắt,
định nghĩa thuật ngữ chưa có sẵn, câu hỏi gợi ý) luôn bám vào nội dung tài liệu: câu hỏi gợi ý phải trỏ về đúng đoạn
sinh ra nó, định nghĩa có sẵn trong tài liệu được lấy nguyên văn.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter

from app.analysis.design import _call, _obj, _text
from app.analysis.evaluation import _content_tokens, _fold

_STR = {"type": "string"}
SUMMARY_CHARS = 6500


def _doc_text(chunks) -> str:
    return "\n\n".join(c.text for c in sorted(chunks, key=lambda c: c.index))


def _sample(chunks, budget: int = SUMMARY_CHARS) -> tuple[str, int]:
    """Lấy phần đầu của mỗi đoạn, chia đều ngân sách ký tự cho mọi đoạn để tóm tắt bao quát cả tài liệu."""
    ordered = sorted(chunks, key=lambda c: c.index)
    per = max(250, budget // max(1, len(ordered)))
    parts = [f"[{c.chunk_id}] {c.text[:per]}" for c in ordered]
    out, used = [], 0
    for part in parts:
        if used + len(part) > budget:
            break
        out.append(part); used += len(part)
    return "\n\n".join(out), len(out)


# ---------------- Mô hình: tóm tắt, câu hỏi gợi ý, định nghĩa thuật ngữ
def _doc_type(value) -> str:
    """Bỏ khi mô hình chép lại chữ mẫu của khuôn thay vì điền loại thật."""
    text = _text(value, 80)
    return "" if not text or "loại tài liệu" in text.casefold() or "ví dụ" in text.casefold() or "/" in text else text


async def summarize(provider, source_name: str, chunks) -> dict:
    text, used = _sample(chunks)
    schema = _obj({"summary": _STR, "key_points": {"type": "array", "items": _STR}, "doc_type": _STR})
    system = ("DOCUMENT_SUMMARIZER. Summarize the technical document for an engineer who has not read it. Use only the "
              "supplied excerpts; do not add facts. Keep identifiers and numbers exact. Return JSON only.")
    user = (f"DOCUMENT: {source_name}\n\nEXCERPTS:\n{text}\n\n"
            'Schema: {"summary":"đoạn văn 80-120 từ","key_points":["5-7 ý chính, mỗi ý một câu"],"doc_type":"tên loại, ví dụ Đặc tả yêu cầu / Thiết kế CSDL / Chính sách bảo mật"}\n'
            "NGÔN NGỮ: tiếng Việt.")
    obj, measured = await _call(provider, system, user, schema, 700)
    return {"summary": _text(obj.get("summary"), 1200), "key_points": [_text(p, 300) for p in (obj.get("key_points") or [])[:7] if _text(p)],
            "doc_type": _doc_type(obj.get("doc_type")), "chunks_read": used, "chunks_total": len(chunks), **measured}


async def suggest_questions(provider, source_name: str, chunks, limit: int = 6) -> dict:
    text, _ = _sample(chunks, 5000)
    ids = [c.chunk_id for c in chunks]
    schema = _obj({"questions": {"type": "array", "items": _obj({"question": _STR, "chunk_id": {"type": "string", "enum": ids}})}})
    system = ("QUESTION_SUGGESTER. Propose questions a team member would ask that the excerpts answer directly. Each "
              "question must be answerable from the excerpt whose chunk_id you give. Prefer concrete rules, limits, "
              "procedures and responsibilities. Return JSON only.")
    user = (f"DOCUMENT: {source_name}\n\nEXCERPTS:\n{text}\n\n"
            'Schema: {"questions":[{"question":"câu hỏi ngắn, kết thúc bằng dấu hỏi","chunk_id":"mã đoạn trả lời được"}]}\n'
            f"Tối đa {limit} câu. NGÔN NGỮ: tiếng Việt.")
    obj, measured = await _call(provider, system, user, schema, 500)
    seen, out = set(), []
    for q in obj.get("questions") or []:
        question = _text(q.get("question"), 200) if isinstance(q, dict) else ""
        if question and q.get("chunk_id") in ids and question.casefold() not in seen:
            seen.add(question.casefold())
            out.append({"question": question if question.endswith("?") else question + "?", "chunk_id": q["chunk_id"]})
    return {"questions": out[:limit], **measured}


_DEFINITION = re.compile(r"^\s*[-*+]\s*\**([^:*\n]{2,40})\**\s*:\s*(.{8,240})$", re.M)
_TECH = re.compile(r"`([^`]{2,40})`|\b([A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]+)?)\b|\b([a-z]+(?:_[a-z0-9]+)+)\b|\b([A-Z][a-z]+[A-Z][A-Za-z]+)\b")
_COMMON_CAPS = {"API", "OK", "ID", "VND", "PK", "FK", "NULL", "NOT", "TRUE", "FALSE", "JSON", "HTTP", "URL", "CSV", "UTC", "GET", "POST"}


def glossary_candidates(text: str, limit: int = 20) -> tuple[list[dict], list[dict]]:
    """(thuật ngữ có định nghĩa sẵn trong tài liệu, thuật ngữ kỹ thuật lặp lại chưa có định nghĩa kèm câu ngữ cảnh)."""
    defined = {}
    for m in _DEFINITION.finditer(text):
        term, definition = m.group(1).strip(" *`"), m.group(2).strip()
        if len(term.split()) <= 5 and term.casefold() not in defined:
            defined[term.casefold()] = {"term": term, "definition": definition, "origin": "document"}
    counts = Counter()
    for m in _TECH.finditer(text):
        term = next(g for g in m.groups() if g)
        if term.upper() not in _COMMON_CAPS and not term.isdigit():
            counts[term] += 1
    sentences = re.split(r"(?<=[.!?])\s+|\n", text)
    pending = []
    for term, n in counts.most_common():
        if n < 2 or term.casefold() in defined or len(pending) >= limit:
            continue
        context = next((s.strip() for s in sentences if term in s and len(s.strip()) > 20), "")
        if context:
            pending.append({"term": term, "context": context[:300], "count": n})
    return list(defined.values())[:40], pending


async def define_terms(provider, pending: list[dict]) -> dict:
    if not pending:
        return {"terms": [], "input_tokens": 0, "output_tokens": 0, "latency_ms": 0}
    names = [p["term"] for p in pending]
    schema = _obj({"terms": {"type": "array", "items": _obj({"term": {"type": "string", "enum": names}, "definition": _STR})}})
    system = ("GLOSSARY_WRITER. Define each technical term in one short sentence for a new team member, using the context "
              "sentence from the project document. If the context is not enough, say what the term refers to in this document "
              "without inventing details. Return JSON only.")
    user = "TERMS WITH CONTEXT:\n" + "\n".join(f"- {p['term']}: {p['context']}" for p in pending) + \
           '\n\nSchema: {"terms":[{"term":"...","definition":"một câu tiếng Việt"}]}'
    obj, measured = await _call(provider, system, user, schema, 900)
    got = {t.get("term"): _text(t.get("definition"), 300) for t in obj.get("terms") or [] if isinstance(t, dict)}
    terms = [{"term": p["term"], "definition": got[p["term"]], "origin": "model", "count": p["count"], "context": p["context"]}
             for p in pending if got.get(p["term"])]
    return {"terms": terms, **measured}


# ---------------- Tại máy: liên quan, chất lượng, thông tin nhạy cảm, so sánh
def related_documents(source_id: str, chunks_by_source: dict[str, list], names: dict[str, str], limit: int = 4) -> list[dict]:
    """Tài liệu cùng chủ đề: độ trùng (cosine) của tần suất từ nội dung, kèm các từ chung nổi bật nhất."""
    vectors = {sid: Counter(t for c in chunks for t in _content_tokens(c.text) if len(t) > 2) for sid, chunks in chunks_by_source.items()}
    base = vectors.get(source_id) or Counter()
    # từ chung hiển thị lại có dấu theo cách viết trong tài liệu gốc
    display = {}
    for c in chunks_by_source.get(source_id, []):
        for w in re.findall(r"\w+", c.text.lower()):
            display.setdefault(_fold(w), w)
    norm = lambda v: sum(x * x for x in v.values()) ** 0.5 or 1.0  # noqa: E731
    out = []
    for sid, vec in vectors.items():
        if sid == source_id:
            continue
        shared = set(base) & set(vec)
        score = sum(base[t] * vec[t] for t in shared) / (norm(base) * norm(vec))
        top = [display.get(t, t) for t in sorted((t for t in shared if len(t) > 3), key=lambda t: -(base[t] * vec[t]))[:6]]
        out.append({"source_id": sid, "source_name": names.get(sid, sid), "score": round(score, 3), "shared_terms": top})
    return sorted(out, key=lambda r: -r["score"])[:limit]


def quality_report(chunks, other_chunks) -> dict:
    """Vấn đề làm hệ thống trả lời kém: tài liệu quá ngắn, ký tự lỗi, đoạn trùng, trùng với tài liệu khác, thiếu đề mục."""
    text = _doc_text(chunks)
    words = len(text.split())
    issues = []
    if words < 150:
        issues.append({"level": "high", "code": "too_short", "message": f"Tài liệu chỉ có {words} từ; quá ít để trả lời câu hỏi chi tiết."})
    bad = text.count("�") + len(re.findall(r"[ÃÂÆ][\x80-\xbf]", text))
    if bad:
        issues.append({"level": "high", "code": "encoding", "message": f"Có {bad} ký tự lỗi mã hóa (ví dụ “�”); nên lưu lại tệp dạng UTF-8 rồi nạp lại."})
    letters = sum(ch.isalpha() for ch in text)
    if text and letters / len(text) < 0.5:
        issues.append({"level": "medium", "code": "low_text", "message": "Tỷ lệ chữ thấp (nhiều ký hiệu, số hoặc bảng); có thể là bản scan hoặc dữ liệu thô."})
    sigs = Counter(" ".join(_content_tokens(c.text)) for c in chunks)
    dup = sum(n - 1 for s, n in sigs.items() if s and n > 1)
    if dup:
        issues.append({"level": "medium", "code": "duplicate_chunks", "message": f"{dup} đoạn trùng nội dung trong cùng tài liệu."})
    own = [set(_content_tokens(c.text)) for c in chunks]
    near = set()
    for oc in other_chunks:
        ot = set(_content_tokens(oc.text))
        if len(ot) >= 15 and any(len(ot & t) / len(ot | t) >= 0.8 for t in own if t):
            near.add(oc.source_name)
    if near:
        issues.append({"level": "medium", "code": "near_duplicate_docs", "message": "Có đoạn gần như trùng hoàn toàn với: " + ", ".join(sorted(near))})
    headings = len(re.findall(r"^\s*#{1,6}\s", text, re.M))
    if words >= 400 and headings == 0:
        issues.append({"level": "low", "code": "no_headings", "message": "Không có đề mục; thêm đề mục giúp tìm đúng phần tài liệu hơn."})
    long_chunks = sum(len(c.text) >= 1150 for c in chunks)
    return {"words": words, "chunks": len(chunks), "headings": headings, "requirement_ids": len(set(re.findall(r"\b(?:FR|NFR|UC|REQ)-\d+", text))),
            "long_chunks": long_chunks, "issues": issues, "score": max(0, 100 - sum({"high": 35, "medium": 15, "low": 5}[i["level"]] for i in issues))}


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


_PII = (
    ("email", "Email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("phone", "Số điện thoại", re.compile(r"(?<!\d)(?:\+84|0)(?:3|5|7|8|9)\d(?:[ .]?\d){7}(?!\d)")),
    ("national_id", "Số CCCD/CMND", re.compile(r"(?i)(?:cccd|cmnd|căn cước|chứng minh)[^\d\n]{0,20}(\d{9}|\d{12})\b")),
    ("bank_account", "Số tài khoản ngân hàng", re.compile(r"(?i)(?:stk|số tài khoản|tài khoản số)[^\d\n]{0,15}(\d{8,15})\b")),
    ("card", "Số thẻ thanh toán", re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")),
    ("secret", "Khóa bí mật / mật khẩu", re.compile(r"\b(?:sk_live|sk_test|whsec|ghp|xox[bp])_[A-Za-z0-9]{12,}\b|(?i:password|mật khẩu|secret)\s*[:=]\s*\S{6,}")),
)


def _mask(value: str) -> str:
    keep = re.sub(r"\s", "", value)
    return keep[:2] + "•" * max(3, len(keep) - 4) + keep[-2:] if len(keep) > 6 else "•" * len(keep)


def pii_scan(text: str) -> dict:
    """Tìm thông tin cá nhân và bí mật; chỉ trả bản đã che, không trả giá trị gốc. Thẻ phải qua kiểm tra Luhn."""
    findings, spans = [], []
    for code, label, pattern in _PII:
        for m in pattern.finditer(text):
            value = m.group(1) if m.groups() and m.group(1) else m.group(0)
            start = m.start(1) if m.groups() and m.group(1) else m.start()
            if code == "card" and not _luhn(re.sub(r"\D", "", value)):
                continue
            if any(s <= start < e for s, e in spans):
                continue
            spans.append((start, start + len(value)))
            line = text.count("\n", 0, start) + 1
            findings.append({"type": code, "label": label, "masked": _mask(value), "line": line})
    masked = text
    for s, e in sorted(spans, reverse=True):
        masked = masked[:s] + "[ĐÃ CHE]" + masked[e:]
    counts = Counter(f["label"] for f in findings)
    return {"findings": findings[:200], "counts": dict(counts), "masked_text": masked}


def compare_versions(old_text: str, new_text: str, limit: int = 300) -> dict:
    """So từng dòng (bỏ khoảng trắng thừa): dòng thêm, bớt, sửa kèm đề mục chứa nó."""
    norm = lambda t: [re.sub(r"\s+", " ", line).strip() for line in t.splitlines() if line.strip()]  # noqa: E731
    a, b = norm(old_text), norm(new_text)
    changes, heading = [], ""
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        for line in b[j1:j2] if tag == "equal" else []:
            heading = line if line.startswith("#") else heading
        if tag == "equal":
            continue
        for line in a[i1:i2]:
            changes.append({"type": "removed" if tag == "delete" else "changed_from", "text": line, "section": heading})
        for line in b[j1:j2]:
            if line.startswith("#"):
                heading = line
            changes.append({"type": "added" if tag == "insert" else "changed_to", "text": line, "section": heading})
    stats = Counter(c["type"] for c in changes)
    return {"changes": changes[:limit], "truncated": len(changes) > limit, "similarity": round(sm.ratio(), 3),
            "added": stats["added"], "removed": stats["removed"], "changed": stats["changed_to"]}


async def summarize_changes(provider, changes: list[dict]) -> dict:
    if not changes:
        return {"summary": "Hai tài liệu giống nhau về nội dung.", "input_tokens": 0, "output_tokens": 0, "latency_ms": 0}
    lines = "\n".join({"added": "+ ", "removed": "- ", "changed_from": "~ cũ: ", "changed_to": "~ mới: "}[c["type"]] + c["text"][:200] for c in changes[:60])
    system = ("CHANGE_SUMMARIZER. Summarize what changed between two versions of a technical document, focusing on rules, "
              "numbers and responsibilities that changed. Use only the diff lines. Return JSON only.")
    obj, measured = await _call(provider, system, f"DIFF:\n{lines}\n\n" + 'Schema: {"summary":"3-5 câu tiếng Việt"}', _obj({"summary": _STR}), 400)
    return {"summary": _text(obj.get("summary"), 1200), **measured}
