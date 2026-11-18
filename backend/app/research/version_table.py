"""Bảng so sánh phiên bản dựng bằng MÃ từ mục diff (mô hình không được viết bảng)."""
from __future__ import annotations

_KIND = {"DOI": "Đổi", "THEM": "Thêm", "BO": "Bỏ"}


def _cell(text, limit: int = 200) -> str:
    text = " ".join(str(text or "").split()).replace("|", "/")
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def _unit(article, clause) -> str:
    return " ".join(x for x in (article, f"khoản {clause}" if clause else "") if x) or "—"


def build_table(evidence) -> str:
    rows = []
    sides: dict = {}
    for c in evidence:
        p = c.provenance or {}
        if p.get("version_unchanged"):
            key = p.get("version_unit")
            sides.setdefault(key, {})[p.get("version_side")] = (p.get("version_label") or "", p.get("version_excerpt") or "", c)
        elif p.get("version_diff"):
            rows.append((p.get("diff_before"), p.get("diff_after"), _KIND.get(p.get("diff_kind"), p.get("diff_kind") or ""),
                         f"{p.get('diff_old_label') or '?'} {_unit(*(p.get('diff_old_unit') or (None, None)))}"
                         f" → {p.get('diff_new_label') or '?'} {_unit(*(p.get('diff_new_unit') or (None, None)))}"))
    for key, pair in sides.items():
        if "before" in pair and "after" in pair and key:
            (ol, ob, _), (nl, na, _) = pair["before"], pair["after"]
            rows.append((ob, na, "Không đổi (cùng giá trị sau chuẩn hóa)",
                         f"{ol} {_unit(key[0], key[1])} → {nl} {_unit(key[2], key[3])}"))
    if not rows:
        return ""
    lines = ["| Cũ | Mới | Thay đổi | Nguồn |", "| --- | --- | --- | --- |"]
    lines += [f"| {_cell(b) or '—'} | {_cell(a) or '—'} | {_cell(k, 60)} | {_cell(s, 160)} |" for b, a, k, s in rows]
    return "\n".join(lines)
