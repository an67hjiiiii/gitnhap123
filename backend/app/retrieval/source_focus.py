"""Đợt 8 Văn phòng 3D (23/11): câu hỏi nêu tên tài liệu thì chỉ tìm trong tài liệu đó.

Vòng đo 1 (office-eval-v1): "theo nội quy…" lại lấy số của quy chế 2024 hoặc đặc tả PayNhanh vì cả kho được tìm chung.
So cụm hai từ của tiêu đề và tên tệp với câu hỏi (bỏ dấu); cụm có ở nhiều tài liệu được tính nhẹ hơn.
Câu có năm (2024, 2026) loại tài liệu mang năm khác. Không chắc thì trả None (tìm cả kho như cũ).
"""
from __future__ import annotations

import re
from collections import defaultdict

from app.analysis.skill_router import is_multi_part
from app.ingestion.doc_type import _fold

_DROP = {"tai", "lieu", "mau", "cong", "ty", "co", "phan", "cua", "va", "md", "docx", "pdf", "txt"}
# cụm thường gặp trong câu hỏi, không đủ để biết người hỏi nói tới tài liệu nào
_COMMON = {"thanh toan", "bao cao", "ke hoach", "du toan", "chi phi", "doanh thu", "hop dong", "co so", "quy dinh"}
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_RULE_DOC_TYPES = frozenset({"legal_doc", "internal_rules", "regulation", "contract", "internal_policy"})
_CROSS_RULE_SIGNAL = re.compile(
    r"\b(so sanh|doi chieu|hieu luc|het hieu luc|toi thieu|lam them|quy dinh|noi quy|phap luat|vi pham|co dung|hop le|tinh tien|chiet khau|tham quyen|bao nhieu)\b"
)


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _fold(text)) if t not in _DROP]


def _bigrams(tokens: list[str]) -> set[str]:
    return {f"{a} {b}" for a, b in zip(tokens, tokens[1:])} - _COMMON


def focus_sources(query: str, chunks, source_ids: list[str] | None, *, allow_multi_part: bool = False) -> list[str] | None:
    titles: dict[str, str] = {}
    doc_types: dict[str, str] = {}
    for c in sorted(chunks, key=lambda c: c.index):
        if c.source_id not in titles and (source_ids is None or c.source_id in source_ids):
            first = next((ln for ln in c.text.splitlines() if ln.strip()), "")
            titles[c.source_id] = re.sub(r"\(.*?\)", " ", first.lstrip("# ")) + " " + re.sub(r"[_\-.]", " ", c.source_name)
            doc_types[c.source_id] = str((c.provenance or {}).get("doc_type") or "other")
    if len(titles) < 2:
        return None
    grams = {sid: _bigrams(_tokens(t)) for sid, t in titles.items()}
    uni = {sid: {w for w in _tokens(t) if len(w) >= 7} for sid, t in titles.items()}
    df: dict[str, int] = defaultdict(int)
    for g in list(grams.values()) + list(uni.values()):
        for x in g:
            df[x] += 1
    q_tokens = _tokens(query)
    q_grams, q_words = _bigrams(q_tokens), set(q_tokens)
    q_years = set(_YEAR.findall(query)) and {m.group(0) for m in _YEAR.finditer(query)}
    scores: dict[str, float] = {}
    base_scores: dict[str, float] = {}
    for sid in titles:
        words = sum(1 / df[g] for g in grams[sid] & q_grams) + sum(2.0 for w in uni[sid] & q_words if df[w] == 1)  # tên riêng (PayNhanh)
        if words <= 0:
            continue
        years = {m.group(0) for m in _YEAR.finditer(titles[sid])}
        if q_years and years:
            if not (years & q_years):
                continue  # câu hỏi nói năm khác
            base_scores[sid] = words
            words += 1.5
        else:
            base_scores[sid] = words
        scores[sid] = words
    if not scores:
        return None
    top = max(scores.values())
    if top < 1.0:
        return None
    top_base = max(base_scores.values())
    keep = [
        sid for sid, v in scores.items()
        if v >= 0.6 * top or (len(scores) >= 2 and base_scores[sid] >= 1.0 and base_scores[sid] >= 0.6 * top_base)
    ]
    q_folded = _fold(query)
    if len(keep) == 1 and not allow_multi_part:
        kept_type = doc_types.get(keep[0], "other")
        other_has_rule = any(doc_types.get(sid, "other") in _RULE_DOC_TYPES for sid in titles if sid != keep[0])
        multi_clause_q = bool(re.search(
            r"\b(?:bao nhieu|the nao|ra sao|o dau|khi nao|nao|gi)\b.*\b(?:va|dong thoi|con)\b.*\b(?:bao nhieu|the nao|ra sao|o dau|khi nao|nao|gi|khong)\b",
            q_folded,
        ))
        if is_multi_part(q_folded) or multi_clause_q or re.search(r"\b(so sanh|doi chieu)\b", q_folded):
            return None  # câu nhiều vế hoặc so sánh chỉ nêu/chỉ giữ một tài liệu: mở rộng tìm toàn kho
        if kept_type not in _RULE_DOC_TYPES and other_has_rule and _CROSS_RULE_SIGNAL.search(q_folded):
            return None  # bảng dữ liệu/số liệu cần đối chiếu thêm văn bản quy định/luật đi kèm
    return keep if len(keep) < len(titles) else None
