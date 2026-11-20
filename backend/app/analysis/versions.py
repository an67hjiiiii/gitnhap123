"""So sánh hai phiên bản văn bản theo Chương/Điều/Khoản (Đợt 4, 20/11). Chỉ dùng mã (difflib), không gọi mô hình.

Bước: tách mỗi bản thành các mục (Điều N, hoặc tiêu đề Markdown/đánh số khi văn bản không có "Điều"); ghép mục hai bản
theo số và độ giống tiêu đề; phân loại THÊM / SỬA / BỎ / GIỮ / DI_CHUYỂN; với mục SỬA, liệt kê khoản thêm/bỏ/sửa.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

VERSION = "version-compare-v1"
SAME_BODY = 0.97      # giống từ ngưỡng này coi là giữ nguyên (chỉ khác khoảng trắng, dấu câu)
TITLE_MATCH = 0.6     # tiêu đề giống từ ngưỡng này coi là cùng một mục dù đổi số
MOVE_BODY = 0.55      # nội dung giống từ ngưỡng này (khác số, tiêu đề lệch) vẫn coi là di chuyển

_ARTICLE = re.compile(r"^\s*(?:#+\s*)?(Điều|ĐIỀU)\s+(\d+[a-zđ]?)\s*[.:\-–]?\s*(.*)$")
_CHAPTER = re.compile(r"^\s*(?:#+\s*)?(Chương|CHƯƠNG)\s+([IVXLC\d]+)\s*[.:\-–]?\s*(.*)$")
_HEADING = re.compile(r"^\s*(#{1,4})\s+(?:(\d+(?:\.\d+)*)[.)]?\s+)?(.+)$")
_CLAUSE = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")


def _fold(s: str) -> str:
    s = (s or "").replace("đ", "d").replace("Đ", "D")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _fold(a), _fold(b), autojunk=False).ratio() if (a or b) else 1.0


@dataclass
class Unit:
    key: str            # "Điều 5" hoặc "3.2" hoặc tiêu đề
    number: str         # số dùng để ghép ("5", "3.2"); rỗng nếu không có
    title: str
    chapter: str = ""
    body: str = ""
    clauses: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"key": self.key, "number": self.number, "title": self.title, "chapter": self.chapter, "body": self.body}


def split_units(text: str) -> list[Unit]:
    """Tách văn bản thành mục. Có "Điều N" thì dùng Điều; không thì dùng tiêu đề Markdown/đánh số."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    by_article = any(_ARTICLE.match(l) for l in lines)
    units: list[Unit] = []
    chapter = ""
    cur: Unit | None = None
    buf: list[str] = []

    def close():
        nonlocal cur, buf
        if cur is not None:
            cur.body = "\n".join(buf).strip()
            for l in buf:
                m = _CLAUSE.match(l)
                if m:
                    cur.clauses[m.group(1)] = m.group(2).strip()
            units.append(cur)
        cur, buf = None, []

    for line in lines:
        mc = _CHAPTER.match(line)
        if mc:
            close()
            chapter = f"Chương {mc.group(2)}" + (f". {mc.group(3).strip()}" if mc.group(3).strip() else "")
            continue
        if by_article:
            m = _ARTICLE.match(line)
            if m:
                close()
                cur = Unit(key=f"Điều {m.group(2)}", number=m.group(2), title=m.group(3).strip(), chapter=chapter)
                continue
        else:
            m = _HEADING.match(line)
            if m and len(m.group(1)) >= 2:  # bỏ tiêu đề cấp 1 (tên văn bản)
                close()
                num, title = m.group(2) or "", m.group(3).strip()
                cur = Unit(key=num or title, number=num, title=title, chapter=chapter)
                continue
        if cur is not None:
            buf.append(line)
    close()
    return units


def _clause_changes(old: Unit, new: Unit) -> list[dict]:
    out = []
    for k in sorted(set(old.clauses) | set(new.clauses), key=lambda x: int(x)):
        a, b = old.clauses.get(k), new.clauses.get(k)
        if a is None:
            out.append({"clause": k, "change": "ADDED", "new": b})
        elif b is None:
            out.append({"clause": k, "change": "REMOVED", "old": a})
        elif not _same(a, b):
            out.append({"clause": k, "change": "MODIFIED", "old": a, "new": b, "similarity": round(_ratio(a, b), 3)})
    return out


def _same(a: str, b: str) -> bool:
    """Giữ nguyên khi gần như trùng chữ VÀ không đổi con số nào (12 → 14 ngày chỉ khác 1 ký tự nhưng là thay đổi thật)."""
    return _ratio(a, b) >= SAME_BODY and not _numbers_changed(a, b)


def _numbers_changed(a: str, b: str) -> list[str]:
    """Con số xuất hiện ở một bản mà không có ở bản kia (ví dụ thời hạn 30 → 45 ngày)."""
    na, nb = Counter(re.findall(r"\d+(?:[.,]\d+)?", a)), Counter(re.findall(r"\d+(?:[.,]\d+)?", b))
    return sorted(set((na - nb) + (nb - na)), key=lambda x: (len(x), x))[:12]  # đếm số lần: "12" còn ở chỗ khác vẫn bắt được


def compare_versions(old_text: str, new_text: str) -> dict:
    old, new = split_units(old_text), split_units(new_text)
    used_new: set[int] = set()
    pairs: list[tuple[Unit | None, Unit | None, str]] = []
    # 1) cùng số và tiêu đề còn giống (hoặc nội dung còn giống): cùng một mục
    for o in old:
        j = next((j for j, n in enumerate(new) if j not in used_new and o.number and n.number == o.number
                  and (_ratio(o.title, n.title) >= TITLE_MATCH or _ratio(o.body, n.body) >= MOVE_BODY)), None)
        if j is not None:
            used_new.add(j)
            pairs.append((o, new[j], "same_number"))
        else:
            pairs.append((o, None, ""))
    # 2) mục chưa ghép: tìm theo tiêu đề hoặc nội dung giống (đổi số = di chuyển)
    for idx, (o, n, how) in enumerate(pairs):
        if n is not None:
            continue
        best, best_score = None, 0.0
        for j, cand in enumerate(new):
            if j in used_new:
                continue
            s = max(_ratio(o.title, cand.title) if o.title and cand.title else 0.0, _ratio(o.body, cand.body) * 0.95)
            if s > best_score:
                best, best_score = j, s
        if best is not None and best_score >= max(TITLE_MATCH, MOVE_BODY):
            used_new.add(best)
            pairs[idx] = (o, new[best], "moved")
    items = []
    for o, n, how in pairs:
        if n is None:
            items.append({"change": "REMOVED", "old": o.to_dict(), "new": None})
            continue
        sim = _ratio(o.body, n.body)
        title_same = _same(o.title, n.title)
        body_same = _same(o.body, n.body)
        if how == "moved" and o.number != n.number:
            change = "MOVED" if body_same and title_same else "MOVED_MODIFIED"
        else:
            change = "UNCHANGED" if body_same and title_same else "MODIFIED"
        item = {"change": change, "old": o.to_dict(), "new": n.to_dict(), "similarity": round(sim, 3)}
        if change in {"MODIFIED", "MOVED_MODIFIED"}:
            item["clauses"] = _clause_changes(o, n)
            item["numbers_changed"] = _numbers_changed(o.body, n.body)
            if not title_same:
                item["title_changed"] = True
        items.append(item)
    for j, n in enumerate(new):
        if j not in used_new:
            items.append({"change": "ADDED", "old": None, "new": n.to_dict()})
    # thứ tự theo bản mới (mục bỏ đứng ở vị trí cũ tương đối)
    def order(it):
        if it["new"] is not None:
            return (next(i for i, n in enumerate(new) if n.to_dict() == it["new"]), 0)
        oi = next(i for i, o in enumerate(old) if o.to_dict() == it["old"])
        return (oi, 1)
    items.sort(key=order)
    counts = {k: sum(1 for it in items if it["change"] == k) for k in ("ADDED", "MODIFIED", "REMOVED", "UNCHANGED", "MOVED", "MOVED_MODIFIED")}
    return {"version": VERSION, "unit_kind": "article" if any(u.key.startswith("Điều") for u in old + new) else "heading",
            "old_units": len(old), "new_units": len(new), "counts": counts, "items": items}
