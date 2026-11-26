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

HYBRID_VERSION = "product-hybrid-bm25-rrf-v3"
RRF_K = 60           # hằng số chuẩn của Reciprocal Rank Fusion
HEADING_WEIGHT = 1.0  # điểm cộng tối đa cho tiêu đề mục, tính bằng đơn vị 1/RRF_K
BM25_STRENGTH_WEIGHT = 1.25  # giữ lợi thế cho đoạn khớp từ khóa hiếm (Uptime, P95, TLS) không bị tiêu đề chung đè
TITLE_WEIGHT = 0.5    # từ của câu hỏi có trong tên tài liệu ("CSDL" ↔ "02_Thiet_ke_CSDL...")
LIST_WEIGHT = 0.5     # câu hỏi liệt kê ("gồm những … nào") ưu tiên mục "Danh sách …", "Các …"
_LIST_Q = re.compile(r"\b(gom|bao gom|liet ke|danh sach|co nhung|nhung .* nao|cac .* nao)\b")
_LIST_H = re.compile(r"\b(danh sach|gom|bao gom)")
BM25_K1, BM25_B = 1.4, 0.75
STRONG_BM25 = 4       # số đoạn khớp từ khóa mạnh luôn được giữ (RET-01)
STRONG_RATIO = 0.6    # "mạnh" = điểm BM25 >= 60% điểm cao nhất
POOL = 3              # lấy vector và BM25 mỗi bên top_k * POOL ứng viên trước khi gộp

# từ chức năng tiếng Việt và tiếng Anh (đã bỏ dấu); không mang nội dung để so khớp
_STOP = {"la", "gi", "nao", "nhung", "cac", "co", "khong", "the", "cua", "cho", "trong", "ve", "va", "duoc", "nay", "mot",
         "bao", "nhieu", "hay", "voi", "khi", "thi", "de", "ai", "o", "dau", "ra", "sao", "nhu", "lam", "gom", "phai", "can",
         "theo", "tu", "den", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "what", "which", "how"}


def fold(text: str) -> str:
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode().lower()


_CAMEL = re.compile(r"([a-z])([A-Z])")


def tokens(text: str) -> list[str]:
    """Âm tiết đã bỏ dấu (bỏ từ chức năng) cộng cặp âm tiết liền nhau; tách cả tên tệp/sheet snake_case và CamelCase (V9)."""
    raw_text = text or ""
    folded = fold(raw_text)
    camel_folded = fold(_CAMEL.sub(r"\1 \2", raw_text))
    raw = re.findall(r"[a-z0-9_]+", camel_folded)
    # Tách thêm các từ con trong định danh có '_' (vd. '02_Bao_Cao_Tai_Chinh_Q4_2025' -> 'bao', 'cao', 'tai', 'chinh'...)
    # đồng thời vẫn giữ nguyên định danh gốc (vd. 'user_id') cho đặc tả phần mềm/SQL.
    words: list[str] = []
    for tok in raw:
        if "_" in tok:
            parts = [p for p in tok.split("_") if p]
            words.extend(parts)
            if len(parts) <= 3:
                words.append(tok)
        else:
            words.append(tok)
    # Giữ thêm token liền gốc nếu CamelCase bị tách (vd. 'vietcore' vẫn còn bên cạnh 'viet', 'core')
    for tok in re.findall(r"[a-z0-9]+", folded):
        if tok not in words and len(tok) >= 4:
            words.append(tok)
    out = [w for w in words if len(w) >= 2 and w not in _STOP]
    plain = [w for w in words if "_" not in w]
    out += [f"{a}_{b}" for a, b in zip(plain, plain[1:]) if a not in _STOP or b not in _STOP]
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
    bm_max = bm[bm_ranked[0]] if bm_ranked else 0.0
    for cid in score:
        c = by_id[cid]
        bonus = HEADING_WEIGHT * heading_match(query, c)
        if bm_max > 0 and cid in bm:
            bonus += BM25_STRENGTH_WEIGHT * (bm[cid] / bm_max)
        if q_words:
            bonus += TITLE_WEIGHT * len(q_words & set(tokens(c.source_name))) / len(q_words)
        if listing and _LIST_H.search(fold(headings(c.text))):
            bonus += LIST_WEIGHT
        score[cid] += bonus / RRF_K
    ranked = sorted(score, key=lambda cid: (-score[cid], cid))[:top_k]
    # BUG-B104-01: cân bằng đa tài liệu khi truy vấn trên >= 2 nguồn (không để 1 nguồn chiếm trọn top_k)
    distinct_sources = {by_id[cid].source_id for cid in score}
    if len(distinct_sources) >= 2 and top_k >= 4:
        max_per_source = max(2, math.ceil(top_k * 0.65))
        all_sorted = sorted(score, key=lambda cid: (-score[cid], cid))
        balanced: list[str] = []
        per_src: Counter[str] = Counter()
        overflow: list[str] = []
        for cid in all_sorted:
            sid = by_id[cid].source_id
            if per_src[sid] < max_per_source:
                balanced.append(cid)
                per_src[sid] += 1
                if len(balanced) >= top_k:
                    break
            else:
                overflow.append(cid)
        if len(balanced) < top_k:
            balanced.extend(overflow[: top_k - len(balanced)])
        ranked = balanced
    # Đoạn khớp từ khóa rất mạnh nhưng vector bỏ qua thì RRF xếp dưới đoạn "vừa vừa" ở cả hai danh sách (bỏ sót Nội quy
    # "gửi đơn trước 03 ngày", 21/11): giữ chắc tối đa STRONG_BM25 đoạn có điểm >= STRONG_RATIO * điểm BM25 cao nhất.
    if bm_ranked:
        strong = [cid for cid in bm_ranked[:STRONG_BM25] if bm[cid] >= STRONG_RATIO * bm[bm_ranked[0]] and cid not in ranked]
        for cid in strong:
            ranked = ranked[:top_k - 1] + [cid] if len(ranked) >= top_k else ranked + [cid]
        ranked = sorted(ranked, key=lambda cid: (-score[cid], cid))
    trace = {"version": HYBRID_VERSION, "vector_candidates": len(vec), "bm25_candidates": len(bm_ranked),
             "from_bm25_only": [cid for cid in ranked if cid not in vec]}
    return [SourceChunk(**{**by_id[cid].__dict__, "score": round(score[cid], 6)}) for cid in ranked], trace


_ARTICLE = re.compile(
    r"(?m)^\s*(?:(?:#{1,4}\s+\S+)|(?:(?:#{1,4}\s*)?(?:(?:Điều|ĐIỀU|Article|Mục|MỤC)\s+\d+|(?:Chương|CHƯƠNG)\s+(?:[IVXLCDM]+|\d+))\s*[.:–-]?))"
)
ARTICLE_TAIL = 400  # Điều hoặc tiêu đề Markdown bắt đầu trong 400 ký tự cuối đoạn thì phần thân/bảng nằm ở đoạn sau


def continue_articles(found: list[SourceChunk], chunks: list[SourceChunk]) -> list[SourceChunk]:
    """Đoạn được chọn kết thúc ngay sau tiêu đề "Điều N." (thân Điều bị cắt sang đoạn sau) thì lấy kèm đoạn liền sau,
    đặt ngay sau đoạn đó. 21/11: "Điều 14. Công nhận tốt nghiệp" nằm cuối đoạn 24, các điều kiện a) b) c) ở đoạn 25,
    mô hình chỉ thấy tiêu đề nên đoán bừa. Chỉ chế độ sản phẩm (gọi trong nhánh hybrid)."""
    by_pos = {(c.source_id, c.index): c for c in chunks}
    have = {c.chunk_id for c in found}
    out: list[SourceChunk] = []
    for c in found:
        out.append(c)
        heads = list(_ARTICLE.finditer(c.text))
        nxt = by_pos.get((c.source_id, c.index + 1))
        tail_stripped = (c.text or "").rstrip()
        mid_sentence_cut = bool(
            len(tail_stripped) >= 500
            and tail_stripped[-1].isalnum()
            and "|" not in tail_stripped.splitlines()[-1]
        )
        if nxt and nxt.chunk_id not in have and (
            (heads and len(c.text) - heads[-1].start() <= ARTICLE_TAIL)
            or mid_sentence_cut
            or (len(tail_stripped) >= 500 and len(nxt.text) <= 300)
        ):
            out.append(SourceChunk(**{**nxt.__dict__, "score": c.score}))
            have.add(nxt.chunk_id)
    return out
