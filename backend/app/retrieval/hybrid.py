"""Truy xuất lai cho chế độ sản phẩm (Đợt 3, 20/11): gộp vector với từ khóa BM25, cộng điểm cho tiêu đề mục khớp câu hỏi.

Chỉ dùng khi pipeline chạy với product_mode=True. Thực nghiệm A/B/C (product_mode=False) giữ truy xuất cũ để số liệu
nghiên cứu tái lập được (kiểm thử test_hybrid_retrieval.py chứng minh).

Lý do: câu hỏi liệt kê ("CSDL gồm những bảng nào?") khớp ý nghĩa với phần mở đầu của mọi tài liệu, nên vector đưa đoạn
đầu lên trước đoạn "Danh sách bảng chính". Từ khóa và tiêu đề mục kéo đúng đoạn lên. Không gọi mô hình sinh.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

from app.core.types import SourceChunk

HYBRID_VERSION = "product-hybrid-bm25-rrf-v2"
RRF_K = 60           # hằng số chuẩn của Reciprocal Rank Fusion
HEADING_WEIGHT = 1.0  # điểm cộng tối đa cho tiêu đề mục, tính bằng đơn vị 1/RRF_K
TITLE_WEIGHT = 0.5    # từ của câu hỏi có trong tên tài liệu ("CSDL" ↔ "02_Thiet_ke_CSDL...")
LIST_WEIGHT = 0.5     # câu hỏi liệt kê ("gồm những … nào") ưu tiên mục "Danh sách …", "Các …"
_LIST_Q = re.compile(r"\b(gom|bao gom|liet ke|danh sach|co nhung|nhung .* nao|cac .* nao)\b")
_LIST_H = re.compile(r"\b(danh sach|gom|bao gom)")
BM25_K1, BM25_B = 1.4, 0.75
POOL = 3              # lấy vector và BM25 mỗi bên top_k * POOL ứng viên trước khi gộp

# từ chức năng tiếng Việt và tiếng Anh (đã bỏ dấu); không mang nội dung để so khớp
_STOP = {"la", "gi", "nao", "nhung", "cac", "co", "khong", "the", "cua", "cho", "trong", "ve", "va", "duoc", "nay", "mot",
         "bao", "nhieu", "hay", "voi", "khi", "thi", "de", "ai", "o", "dau", "ra", "sao", "nhu", "lam", "gom", "phai", "can",
         "theo", "tu", "den", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "what", "which", "how"}


def fold(text: str) -> str:
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode().lower()


def tokens(text: str) -> list[str]:
    """Âm tiết đã bỏ dấu (bỏ từ chức năng) cộng cặp âm tiết liền nhau, vì từ tiếng Việt thường gồm hai âm tiết."""
    words = re.findall(r"[a-z0-9_]+", fold(text))
    out = [w for w in words if len(w) >= 2 and w not in _STOP]
    out += [f"{a}_{b}" for a, b in zip(words, words[1:]) if a not in _STOP or b not in _STOP]
    return out


def headings(text: str) -> str:
    """Dòng tiêu đề trong đoạn: dòng Markdown '#', hoặc dòng ngắn đánh số ('3.2 Bảng refunds', 'Điều 5. ...')."""
    keep = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("#") or (len(s) <= 90 and re.match(r"^((\d+(\.\d+)*)|(dieu|chuong|muc|khoan)\s+\d+)[.)\s]", fold(s))):
            keep.append(s.lstrip("# "))
    return "\n".join(keep)


def bm25_scores(query: str, chunks: list[SourceChunk]) -> dict[str, float]:
    q = set(tokens(query))
    if not q or not chunks:
        return {}
    docs = {c.chunk_id: Counter(tokens(c.text)) for c in chunks}
    avg = sum(sum(d.values()) for d in docs.values()) / len(docs) or 1.0
    df = Counter(t for d in docs.values() for t in set(d) & q)
    n = len(docs)
    out: dict[str, float] = {}
    for cid, d in docs.items():
        length = sum(d.values()) or 1
        s = 0.0
        for t in q & set(d):
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            tf = d[t]
            s += idf * tf * (BM25_K1 + 1) / (tf + BM25_K1 * (1 - BM25_B + BM25_B * length / avg))
        if s > 0:
            out[cid] = s
    return out


def heading_match(query: str, chunk: SourceChunk) -> float:
    """Tỷ lệ từ nội dung của câu hỏi xuất hiện trong tiêu đề mục của đoạn (0..1)."""
    q = {t for t in tokens(query) if "_" not in t}
    if not q:
        return 0.0
    h = set(tokens(headings(chunk.text)))
    return len(q & h) / len(q)


def fuse(query: str, chunks: list[SourceChunk], vector_ranked: list[str], top_k: int) -> tuple[list[SourceChunk], dict]:
    """Gộp thứ hạng vector (đã lọc quyền, ngưỡng) với BM25 trên cùng tập đoạn của chủ sở hữu bằng RRF + điểm tiêu đề."""
    by_id = {c.chunk_id: c for c in chunks}
    bm = bm25_scores(query, chunks)
    bm_ranked = sorted(bm, key=lambda cid: (-bm[cid], cid))[: top_k * POOL]
    vec = [cid for cid in vector_ranked if cid in by_id][: top_k * POOL]
    score: dict[str, float] = {}
    for rank, cid in enumerate(vec):
        score[cid] = score.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, cid in enumerate(bm_ranked):
        score[cid] = score.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    q_words = {t for t in tokens(query) if "_" not in t}
    listing = bool(_LIST_Q.search(fold(query)))
    for cid in score:
        c = by_id[cid]
        bonus = HEADING_WEIGHT * heading_match(query, c)
        if q_words:
            bonus += TITLE_WEIGHT * len(q_words & set(tokens(c.source_name))) / len(q_words)
        if listing and _LIST_H.search(fold(headings(c.text))):
            bonus += LIST_WEIGHT
        score[cid] += bonus / RRF_K
    ranked = sorted(score, key=lambda cid: (-score[cid], cid))[:top_k]
    trace = {"version": HYBRID_VERSION, "vector_candidates": len(vec), "bm25_candidates": len(bm_ranked),
             "from_bm25_only": [cid for cid in ranked if cid not in vec]}
    return [SourceChunk(**{**by_id[cid].__dict__, "score": round(score[cid], 6)}) for cid in ranked], trace
