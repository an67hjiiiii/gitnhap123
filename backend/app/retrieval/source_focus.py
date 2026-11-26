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

_DROP = {"tai", "lieu", "mau", "cong", "ty", "co", "phan", "cua", "va", "md", "docx", "pdf", "txt", "xlsx", "csv", "xls"}
# cụm thường gặp trong câu hỏi, không đủ để biết người hỏi nói tới tài liệu nào
_COMMON = {"thanh toan", "bao cao", "ke hoach", "du toan", "chi phi", "doanh thu", "hop dong", "co so", "quy dinh"}
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _fold(text)) if t not in _DROP]


def _bigrams(tokens: list[str]) -> set[str]:
    return {f"{a} {b}" for a, b in zip(tokens, tokens[1:])} - _COMMON


def _family_stem(title: str) -> set[str]:
    """Các từ đặc trưng nhận diện cùng họ tài liệu (bỏ năm và số phiên bản) để chỉ lọc chéo phiên bản cùng loại."""
    return {t for t in _tokens(title) if not _YEAR.fullmatch(t) and not t.isdigit() and len(t) >= 2}


def has_same_family_for_years(target_title: str, all_titles: dict[str, str], q_years: set[str], *, exclude_sid: str | None = None) -> bool:
    """True khi tồn tại tài liệu khác CÙNG HỌ (vd. Quy chế 2024 vs Quy chế 2026) mang đúng năm q_years."""
    target_stem = _family_stem(target_title)
    if not target_stem or not q_years:
        return False
    for sid, other_title in all_titles.items():
        if sid == exclude_sid:
            continue
        norm_other = re.sub(r"[_\-.]", " ", other_title)
        other_years = {m.group(0) for m in _YEAR.finditer(norm_other)}
        if not (other_years & q_years):
            continue
        other_stem = _family_stem(norm_other)
        overlap = target_stem & other_stem
        if len(overlap) >= 2 and (len(overlap) / max(1, min(len(target_stem), len(other_stem)))) >= 0.45:
            return True
    return False


def focus_sources(query: str, chunks, source_ids: list[str] | None, *, allow_multi_part: bool = False) -> list[str] | None:
    titles: dict[str, str] = {}
    for c in sorted(chunks, key=lambda c: c.index):
        if c.source_id not in titles and (source_ids is None or c.source_id in source_ids):
            first = next((ln for ln in c.text.splitlines() if ln.strip()), "")
            titles[c.source_id] = re.sub(r"\(.*?\)", " ", first.lstrip("# ")) + " " + re.sub(r"[_\-.]", " ", c.source_name)
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
    for sid in titles:
        words = sum(1 / df[g] for g in grams[sid] & q_grams) + sum(2.0 for w in uni[sid] & q_words if df[w] == 1)  # tên riêng (PayNhanh)
        if words <= 0:
            continue
        years = {m.group(0) for m in _YEAR.finditer(titles[sid])}
        if q_years and years:
            if not (years & q_years):
                if has_same_family_for_years(titles[sid], titles, q_years, exclude_sid=sid):
                    continue  # chỉ loại bản cũ cùng họ (vd. Quy chế 2024 khi đã có Quy chế 2026)
            else:
                words += 1.5
        scores[sid] = words
    if not scores:
        return None
    top = max(scores.values())
    if top < 1.0:
        return None
    keep = [sid for sid, v in scores.items() if v >= 0.6 * top]
    if len(keep) == 1 and not allow_multi_part and is_multi_part(_fold(query)):
        return None  # câu nhiều vế chỉ nêu một tài liệu: vế kia có thể ở tài liệu khác
    return keep if len(keep) < len(titles) else None
