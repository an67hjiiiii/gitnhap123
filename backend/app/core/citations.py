from __future__ import annotations

import re
import unicodedata
from app.core.types import SourceChunk


def validate_citations(citation_ids: list[str], available: list[SourceChunk]) -> tuple[list[str], list[str]]:
    allowed = {c.chunk_id for c in available}
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for cid in citation_ids:
        cid = str(cid).strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        if cid in allowed:
            valid.append(cid)
        else:
            invalid.append(cid)
    return valid, invalid


_CHUNK_ID_RE = re.compile(r"(src_[0-9a-f]+_c\d+)", re.IGNORECASE)
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_STOP_FOLD = {
    "va", "la", "cua", "cho", "trong", "voi", "mot", "cac", "nhung", "duoc",
    "khong", "co", "theo", "tu", "den", "tai", "lieu", "thong", "tin", "quy",
    "dinh", "chinh", "sach", "hien", "nay", "nam", "thang", "ngay", "muc", "bao",
    "nhieu", "phan", "nay", "tren", "duoi", "sau", "truoc", "khi", "thi", "neu",
}


def _fold_ci(text: str) -> str:
    s = (text or "").replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()


def _content_tokens(text: str) -> set[str]:
    words = [w for w in re.findall(r"[a-z0-9]{2,}", _fold_ci(text)) if w not in _STOP_FOLD]
    out = set(words)
    for a, b in zip(words, words[1:]):
        out.add(f"{a}_{b}")
    return out


def _significant_numbers(text: str) -> set[str]:
    nums: set[str] = set()
    for m in _NUM_RE.findall(text or ""):
        clean = m.replace(".", "").replace(",", "")
        if len(clean) >= 2:
            nums.add(clean)
            nums.add(m)
    return nums


def resolve_citations(
    citation_ids: list[str],
    available: list[SourceChunk],
    answer_text: str = "",
    *,
    allow_grounded_fallback: bool = True,
) -> tuple[list[str], list[str]]:
    """Chuẩn hóa & xác thực citation trên tập `available` cho chế độ sản phẩm.

    1. Chấp nhận mã bị bọc ngoặc/khoảng trắng hoặc lệch hoa-thường nếu khớp duy nhất 1 chunk hợp lệ.
    2. Nếu mô hình nhỏ (4B) trả lời có nội dung thật từ bằng chứng nhưng quên ghi citations,
       đối chiếu số liệu và cụm từ 2 tiếng trong `answer_text` với `available` để truy vết đúng chunk gốc.
    """
    if not available:
        return validate_citations(citation_ids, available)

    lower_map = {c.chunk_id.casefold(): c.chunk_id for c in available}
    suffix_map: dict[str, list[str]] = {}
    for c in available:
        tail = c.chunk_id.rsplit("_", 1)[-1].casefold()
        suffix_map.setdefault(tail, []).append(c.chunk_id)

    normalized: list[str] = []
    for raw in citation_ids:
        s = str(raw or "").strip().strip("[]()\"' ")
        if not s:
            continue
        m = _CHUNK_ID_RE.search(s)
        cand = m.group(1) if m else s
        if cand.casefold() in lower_map:
            normalized.append(lower_map[cand.casefold()])
            continue
        # Khớp hậu tố c0001 nếu chỉ có 1 nguồn ứng viên mang hậu tố đó
        if re.fullmatch(r"c\d+", cand, re.IGNORECASE):
            matches = suffix_map.get(cand.casefold(), [])
            if len(matches) == 1:
                normalized.append(matches[0])
                continue
        normalized.append(s)

    # Lấy thêm mã HỢP LỆ nhúng trong prose (nếu mô hình viết trong văn bản nhưng quên điền mảng citations);
    # bỏ qua mã gõ nhầm 1 ký tự trong prose để không biến nó thành invalid citation làm hạ oan COMPLETE → PARTIAL.
    for raw in _CHUNK_ID_RE.findall(answer_text or ""):
        if raw.casefold() in lower_map:
            normalized.append(lower_map[raw.casefold()])

    valid, invalid = validate_citations(normalized, available)
    if not allow_grounded_fallback or not (answer_text or "").strip():
        return valid, invalid

    ans_nums = _significant_numbers(answer_text)
    ans_toks = _content_tokens(answer_text)
    ans_bigrams = {t for t in ans_toks if "_" in t}

    if valid:
        by_id = {c.chunk_id: c for c in available}

        def _chunk_support(ch: SourceChunk) -> tuple[int, int]:
            c_nums = _significant_numbers(ch.text)
            c_bigrams = {t for t in _content_tokens(ch.text) if "_" in t}
            return len(ans_nums & c_nums), len(ans_bigrams & c_bigrams)

        # Bổ sung nguồn bị quên trên câu hỏi đa tài liệu trước, sau đó tỉa bỏ nguồn gán nhầm (0 số khớp & <=1 cụm từ khớp)
        covered_nums: set[str] = set()
        covered_bigrams: set[str] = set()
        for cid in valid:
            ch = by_id.get(cid)
            if ch is None:
                continue
            covered_nums |= _significant_numbers(ch.text)
            covered_bigrams |= {t for t in _content_tokens(ch.text) if "_" in t}
        uncovered_nums = ans_nums - covered_nums
        uncovered_bigrams = ans_bigrams - covered_bigrams
        valid_set = set(valid)
        extras: list[str] = []
        if uncovered_nums or uncovered_bigrams:
            for _ in range(2):
                best_score = 0.0
                best_chunk: SourceChunk | None = None
                for c in available:
                    if c.chunk_id in valid_set:
                        continue
                    c_nums = _significant_numbers(c.text)
                    c_bigrams = {t for t in _content_tokens(c.text) if "_" in t}
                    num_gain = len(uncovered_nums & c_nums)
                    bi_gain = len(uncovered_bigrams & c_bigrams)
                    if num_gain >= 2 or (num_gain >= 1 and bi_gain >= 1) or bi_gain >= 3:
                        sc = num_gain * 3.0 + bi_gain * 1.5
                        if sc > best_score:
                            best_score = sc
                            best_chunk = c
                if best_chunk is None:
                    break
                valid_set.add(best_chunk.chunk_id)
                extras.append(best_chunk.chunk_id)
                uncovered_nums -= _significant_numbers(best_chunk.text)
                uncovered_bigrams -= {t for t in _content_tokens(best_chunk.text) if "_" in t}
                if not uncovered_nums and not uncovered_bigrams:
                    break

        combined = [*valid, *extras]
        # Grounded Citation Pruning: nếu đã có chunk hỗ trợ trực tiếp (khớp số liệu hoặc >=3 cụm 2 tiếng),
        # loại bỏ các chunk bị mô hình 4B cite nhầm (0 số khớp và <=1 cụm từ chung như tên công ty).
        if len(combined) > 1:
            supports = {cid: _chunk_support(by_id[cid]) for cid in combined if cid in by_id}
            has_strong = any(nh >= 1 or bh >= 3 for nh, bh in supports.values())
            if has_strong:
                pruned = [cid for cid in combined if supports.get(cid, (0, 0))[0] >= 1 or supports.get(cid, (0, 0))[1] >= 2]
                if pruned:
                    combined = pruned
        return combined, invalid

    # Grounded fallback khi mô hình quên điền toàn bộ citations:
    scored: list[tuple[float, str]] = []
    for c in available:
        c_nums = _significant_numbers(c.text)
        c_toks = _content_tokens(c.text)
        c_bigrams = {t for t in c_toks if "_" in t}
        num_hits = len(ans_nums & c_nums)
        bi_hits = len(ans_bigrams & c_bigrams)
        word_hits = len((ans_toks - ans_bigrams) & (c_toks - c_bigrams))
        score = num_hits * 2.5 + bi_hits * 1.4 + word_hits * 0.35
        if num_hits >= 1 or bi_hits >= 2 or word_hits >= 5:
            scored.append((score, c.chunk_id))
    if not scored:
        return valid, invalid
    scored.sort(key=lambda x: (-x[0], x[1]))
    top_score = scored[0][0]
    recovered = [cid for sc, cid in scored[:3] if sc >= max(2.2, top_score * 0.65)]
    return recovered, []
