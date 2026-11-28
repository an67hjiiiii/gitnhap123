from __future__ import annotations
import hashlib
import re
import unicodedata
from collections.abc import Mapping
from typing import Any
from app.core.types import SourceChunk

STOP = {"the","a","an","and","or","to","of","in","on","for","with","is","are","be","this","that","và","là","của","cho","trong","với","một","các","những","được","hãy","theo"}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", str(text or ""))
    return text.replace("\ufeff", "", 1).replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def estimate_tokens(text: str) -> int:
    """Tokenizer-independent conservative proxy used only for pre-call budgeting.

    Actual provider-reported token counts remain authoritative in run metrics.
    """
    clean = normalize_text(text)
    if not clean:
        return 0
    # Mixed Vietnamese/English text generally lands near 3-4 chars/token.
    return max(1, (len(clean) + 2) // 3)


def _stem_token(token: str) -> str:
    # Tiny deterministic English normalization; intentionally not a learned stemmer.
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token

def terms(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-zÀ-ỹ0-9_'-]{2,}", normalize_text(text).lower())
    expanded = {piece for token in raw for piece in (token, *re.split(r"[_'-]", token)) if len(piece) >= 2}
    normalized = {_stem_token(t) for t in expanded if t not in STOP}
    return normalized


_HEADING_MD_RE = re.compile(r"^#{1,6}\s+\S")
_HEADING_NUM_RE = re.compile(
    r"^(?:(?:chương|phần|mục|điều|phụ\s*lục|section|article|chapter)\s+[IVXLC\d]+|\d+(?:\.\d+)*[.)]\s+\S)",
    re.IGNORECASE,
)
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]{3,}\|?\s*$")


def _is_heading_line(line: str) -> bool:
    s = line.strip()
    if not s or "|" in s:
        return False
    if _HEADING_MD_RE.match(s):
        return True
    if len(s) <= 105 and not s.endswith((".", ";", ",")) and _HEADING_NUM_RE.match(s):
        # Tránh nhầm danh sách bước dài "1. Nhân viên gửi đơn..." thành tiêu đề khi không phải mục lớn
        if re.match(r"^\d+\.\s+", s) and len(s) > 72:
            return False
        return True
    if 8 <= len(s) <= 100 and s == s.upper() and any(ch.isalpha() for ch in s):
        return True
    return False


def _is_table_block(block: str) -> bool:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    pipe_lines = [ln for ln in lines if "|" in ln]
    return len(pipe_lines) >= 2


def _extract_heading_label(chunk: str) -> str:
    for ln in chunk.splitlines():
        s = ln.strip()
        if not s:
            continue
        if _HEADING_MD_RE.match(s):
            return re.sub(r"^#{1,6}\s+", "", s).strip()[:96]
        if _is_heading_line(s):
            return s[:96]
    return ""


def _split_into_atomic_blocks(text: str) -> list[str]:
    """Tách văn bản theo đoạn trống và tách thêm tại ranh giới dòng tiêu đề Markdown/Mục để không dính mục sau vào mục trước."""
    raw_parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    blocks: list[str] = []
    for part in raw_parts:
        lines = part.splitlines()
        if len(lines) <= 1:
            blocks.append(part)
            continue
        # Nếu block là sheet Excel/Markdown dạng "## Sheet\nHeader | Col\nRow1..." thì giữ nguyên nhóm
        if _HEADING_MD_RE.match(lines[0].strip()) and _is_table_block("\n".join(lines[1:])):
            blocks.append(part)
            continue
        cur: list[str] = []
        for idx, ln in enumerate(lines):
            stripped = ln.strip()
            if idx > 0 and stripped and (_HEADING_MD_RE.match(stripped) or _is_heading_line(stripped)) and cur:
                blocks.append("\n".join(cur).strip())
                cur = [ln]
            else:
                cur.append(ln)
        if cur:
            joined = "\n".join(cur).strip()
            if joined:
                blocks.append(joined)
    return blocks


def _split_table_block(block: str, max_chars: int, context_heading: str) -> list[str]:
    """Tách bảng dài theo ranh giới hàng và lặp lại dòng tiêu đề cột (header) ở mỗi đoạn con."""
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
    if not lines:
        return []
    prefix_lines: list[str] = []
    body_start = 0
    if _HEADING_MD_RE.match(lines[0].strip()):
        prefix_lines.append(lines[0].strip())
        body_start = 1
    elif context_heading and not any(context_heading in ln for ln in lines[:2]):
        prefix_lines.append(context_heading)

    if body_start < len(lines) and "|" in lines[body_start]:
        prefix_lines.append(lines[body_start])
        body_start += 1
        if body_start < len(lines) and _TABLE_SEP_RE.match(lines[body_start]):
            prefix_lines.append(lines[body_start])
            body_start += 1

    header = "\n".join(prefix_lines).strip()
    rows = lines[body_start:]
    if not rows:
        return [block]

    chunks: list[str] = []
    cur = header
    for row in rows:
        candidate = f"{cur}\n{row}" if cur else row
        if len(candidate) <= max_chars or cur == header:
            cur = candidate
        else:
            chunks.append(cur.strip())
            cur = f"{header}\n{row}" if header else row
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _split_long_text(block: str, max_chars: int, context_heading: str) -> list[str]:
    """Tách đoạn văn dài theo dòng / câu / khoảng trắng (không cắt ngang từ hoặc con số), giữ ngữ cảnh tiêu đề cha."""
    prefix = f"{context_heading}\n" if context_heading and not block.lstrip().startswith(context_heading) else ""
    usable = max(200, max_chars - len(prefix))

    # Tách theo dòng trước; nếu một dòng đơn lẻ vẫn dài hơn usable thì tách theo câu
    units: list[str] = []
    for ln in block.splitlines():
        s = ln.strip()
        if not s:
            continue
        if len(s) <= usable:
            units.append(s)
        else:
            sentences = re.split(r"(?<=[.!?;])\s+", s)
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                if len(sent) <= usable:
                    units.append(sent)
                else:
                    # Tách theo từ (không bao giờ cắt đứt giữa từ hay con số)
                    words = sent.split()
                    acc = ""
                    for w in words:
                        if not acc:
                            acc = w
                        elif len(acc) + 1 + len(w) <= usable:
                            acc += " " + w
                        else:
                            units.append(acc)
                            acc = w
                    if acc:
                        units.append(acc)

    chunks: list[str] = []
    buf = ""
    for u in units:
        if not buf:
            buf = u
        elif len(buf) + 1 + len(u) <= usable:
            buf += "\n" + u
        else:
            chunks.append((prefix + buf).strip() if chunks or not block.lstrip().startswith(context_heading) else buf.strip())
            buf = u
    if buf:
        chunks.append((prefix + buf).strip() if chunks else buf.strip())
    return chunks


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    """Chia đoạn có nhận thức cấu trúc (Structure-Aware Chunking):
    - Ưu tiên tách tại ranh giới tiêu đề mục để mỗi đoạn gắn đúng chủ đề.
    - Không bao giờ để tiêu đề mồ côi ở cuối đoạn trước.
    - Bảng dài được tách theo hàng và tự động lặp lại dòng tiêu đề cột.
    - Đoạn dài chỉ cắt theo ranh giới dòng/câu/từ và kế thừa tiêu đề mục cha.
    """
    text = normalize_text(text)
    if not text:
        return []
    blocks = _split_into_atomic_blocks(text)
    chunks: list[str] = []
    buf_blocks: list[str] = []
    buf_len = 0
    buf_has_body = False
    current_heading = ""

    def flush_buf() -> None:
        nonlocal buf_blocks, buf_len, buf_has_body
        if buf_blocks:
            chunks.append("\n\n".join(buf_blocks).strip())
            buf_blocks = []
            buf_len = 0
            buf_has_body = False

    for idx, block in enumerate(blocks):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        is_pure_heading = len(lines) == 1 and _is_heading_line(lines[0])
        starts_with_heading = bool(lines) and _is_heading_line(lines[0])
        is_table = _is_table_block(block)

        # Khi gặp tiêu đề mục mới mà buffer hiện tại đã chứa nội dung thực sự (mục trước),
        # chủ động ngắt đoạn để mục mới bắt đầu sạch sẽ với đúng tiêu đề của nó!
        if starts_with_heading and buf_has_body and (buf_len >= 220 or any(_is_table_block(b) for b in buf_blocks) or is_table):
            flush_buf()

        if starts_with_heading:
            current_heading = lines[0]

        # Xử lý block lớn hơn max_chars
        if len(block) > max_chars:
            # Nếu buffer hiện chỉ là tiêu đề chờ ghép với block lớn này -> giữ làm ngữ cảnh rồi xóa khỏi buffer
            heading_for_split = current_heading
            if buf_blocks and not buf_has_body:
                heading_for_split = buf_blocks[-1]
                buf_blocks = []
                buf_len = 0
            else:
                flush_buf()
            if is_table:
                chunks.extend(_split_table_block(block, max_chars, heading_for_split))
            else:
                chunks.extend(_split_long_text(block, max_chars, heading_for_split))
            continue

        # Không để tiêu đề nằm mồ côi ở cuối đoạn: kiểm tra nếu thêm tiêu đề + đoạn kế tiếp sẽ tràn max_chars
        if is_pure_heading and buf_has_body:
            next_len = len(blocks[idx + 1]) if idx + 1 < len(blocks) else 0
            if buf_len + len(block) + next_len + 4 > max_chars:
                flush_buf()

        sep = 2 if buf_blocks else 0
        if buf_len + sep + len(block) <= max_chars:
            buf_blocks.append(block)
            buf_len += sep + len(block)
            if not is_pure_heading:
                buf_has_body = True
        else:
            flush_buf()
            # Nếu block nội dung sang đoạn mới mà không tự mang tiêu đề, gắn tiêu đề mục cha để không mồ côi ngữ cảnh
            if not starts_with_heading and current_heading and len(current_heading) + 2 + len(block) <= max_chars:
                buf_blocks = [current_heading, block]
                buf_len = len(current_heading) + 2 + len(block)
            else:
                buf_blocks = [block]
                buf_len = len(block)
            buf_has_body = not is_pure_heading

    flush_buf()
    return chunks


def make_chunks(
    source_name: str,
    text: str,
    max_chars: int = 1200,
    *,
    provenance: Mapping[str, Any] | None = None,
) -> list[SourceChunk]:
    clean = normalize_text(text)
    source_id = "src_" + hashlib.sha256((source_name + "\0" + clean).encode()).hexdigest()[:16]
    base_provenance = dict(provenance or {})
    result: list[SourceChunk] = []
    for i, chunk in enumerate(chunk_text(clean, max_chars=max_chars)):
        sec_heading = _extract_heading_label(chunk)
        est_tokens = estimate_tokens(chunk)
        result.append(SourceChunk(
            chunk_id=f"{source_id}_c{i:04d}",
            source_id=source_id,
            source_name=source_name,
            text=chunk,
            index=i,
            provenance={
                **base_provenance,
                "chunk_index": i,
                "estimated_tokens": est_tokens,
                **({"section_heading": sec_heading} if sec_heading else {}),
            },
        ))
    return result


def lexical_score(query: str, chunk: SourceChunk) -> float:
    q = terms(query)
    c = terms(chunk.text)
    if not q or not c:
        return 0.0
    overlap = len(q & c)
    coverage = overlap / max(1, len(q))
    density = overlap / max(1, len(c))
    return round(0.8 * coverage + 0.2 * density, 8)


def retrieve(query: str, chunks: list[SourceChunk], top_k: int = 6, min_score: float = 0.0) -> list[SourceChunk]:
    scored: list[SourceChunk] = []
    for chunk in chunks:
        score = lexical_score(query, chunk)
        if score >= min_score and score > 0:
            scored.append(SourceChunk(**{**chunk.__dict__, "score": score}))
    scored.sort(key=lambda x: (-x.score, x.chunk_id))
    return scored[:top_k]


def _source_aware_relevance(query: str, chunk: SourceChunk) -> tuple[float, float]:
    """Đo mức khớp truy vấn trên cả tên nguồn (năm, mã luật) lẫn nội dung đoạn."""
    q = terms(query)
    if not q:
        return (0.0, 0.0)
    combined = terms(f"{chunk.source_name} {chunk.text}")
    coverage = round(len(q & combined) / len(q), 4)
    return (coverage, round(lexical_score(query, chunk), 4))


def select_budgeted_chunks(
    chunks: list[SourceChunk],
    *,
    cost_fn,
    budget: int,
    query: str | None = None,
    truncate_first: bool = False,
    budget_reason: str = "token_budget_proxy",
    dedup_exact: bool = True,
    priority_ids: set[str] | None = None,
) -> tuple[list[SourceChunk], list[dict]]:
    """Bộ chọn đoạn dùng chung cho char-proxy và token-budget: bảo toàn đa nguồn + đoạn nối tiếp theo đúng truy vấn."""
    if not chunks:
        return [], []
    prio_set = priority_ids or set()
    if not query or len({c.source_id for c in chunks}) < 2:
        selected: list[SourceChunk] = []
        dropped: list[dict] = []
        seen_exact: set[str] = set()
        used = 0
        for chunk in chunks:
            digest = hashlib.sha256(chunk.text.strip().encode()).hexdigest()
            if dedup_exact and chunk.chunk_id not in prio_set and digest in seen_exact:
                dropped.append({"chunk_id": chunk.chunk_id, "reason": "exact_duplicate"})
                continue
            cost = cost_fn(chunk.text)
            if (selected or not truncate_first) and used + cost > budget:
                dropped.append({"chunk_id": chunk.chunk_id, "reason": budget_reason, "estimated_tokens": cost})
                continue
            if not selected and truncate_first and cost > budget:
                char_cap = max(128, budget * 3)
                excerpt = chunk.text[:char_cap]
                selected.append(SourceChunk(**{**chunk.__dict__, "text": excerpt}))
                used += cost_fn(excerpt)
                dropped.append({"chunk_id": chunk.chunk_id, "reason": "truncated_to_hard_context_token_cap", "estimated_tokens": cost})
                continue
            if dedup_exact:
                seen_exact.add(digest)
            selected.append(chunk)
            used += cost
        return selected, dropped

    picked: list[SourceChunk] = []
    picked_ids: set[str] = set()
    seen_exact: set[str] = set()
    dropped = []
    used = 0

    def _try_take(chunk: SourceChunk) -> bool:
        nonlocal used
        if chunk.chunk_id in picked_ids:
            return False
        digest = hashlib.sha256(chunk.text.strip().encode()).hexdigest()
        if digest in seen_exact:
            return False
        cost = cost_fn(chunk.text)
        if (picked or not truncate_first) and used + cost > budget:
            return False
        if not picked and truncate_first and cost > budget:
            char_cap = max(128, budget * 3)
            excerpt = chunk.text[:char_cap]
            picked.append(SourceChunk(**{**chunk.__dict__, "text": excerpt}))
            picked_ids.add(chunk.chunk_id)
            seen_exact.add(digest)
            used += cost_fn(excerpt)
            return True
        seen_exact.add(digest)
        picked_ids.add(chunk.chunk_id)
        picked.append(chunk)
        used += cost
        return True

    by_src: dict[str, list[SourceChunk]] = {}
    for c in chunks:
        by_src.setdefault(c.source_id, []).append(c)

    ranked_sources: list[tuple[tuple[float, float, float], SourceChunk, list[SourceChunk]]] = []
    for src_chunks in by_src.values():
        best = max(src_chunks, key=lambda c: (*_source_aware_relevance(query, c), float(c.score or 0.0), -c.index))
        cov, lex = _source_aware_relevance(query, best)
        ranked_sources.append(((cov, lex, float(best.score or 0.0)), best, src_chunks))
    ranked_sources.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], item[1].chunk_id))

    seeded: list[tuple[SourceChunk, list[SourceChunk]]] = []
    for _, best, src_chunks in ranked_sources:
        if _try_take(best):
            seeded.append((best, src_chunks))

    for best, src_chunks in seeded:
        nxt = next((c for c in src_chunks if c.index == best.index + 1), None)
        if nxt is None:
            nxt = next((c for c in src_chunks if c.index == best.index - 1), None)
        if nxt is not None:
            _try_take(nxt)

    for chunk in chunks:
        if chunk.chunk_id in picked_ids:
            continue
        digest = hashlib.sha256(chunk.text.strip().encode()).hexdigest()
        if digest in seen_exact:
            dropped.append({"chunk_id": chunk.chunk_id, "reason": "exact_duplicate"})
            continue
        cost = cost_fn(chunk.text)
        if not _try_take(chunk):
            dropped.append({"chunk_id": chunk.chunk_id, "reason": budget_reason, "estimated_tokens": cost})
    return picked, dropped


def apply_token_budget(
    chunks: list[SourceChunk],
    max_tokens: int,
    *,
    query: str | None = None,
    priority_ids: set[str] | None = None,
) -> tuple[list[SourceChunk], list[dict]]:
    # BUG-B109-01: ưu tiên giữ lại các đoạn được BM25 cứu (from_bm25_only) khi chạm trần ngân sách token
    ordered = list(chunks)
    if priority_ids:
        prio = [c for c in ordered if c.chunk_id in priority_ids]
        rest = [c for c in ordered if c.chunk_id not in priority_ids]
        if prio and rest:
            # Giữ nguyên top 2 ứng viên cao nhất, đặt priority BM25 ngay sau để không bị cắt đuôi
            ordered = rest[:2] + prio + rest[2:]
    return select_budgeted_chunks(
        ordered,
        cost_fn=estimate_tokens,
        budget=max_tokens,
        query=query,
        truncate_first=True,
        budget_reason="hard_context_token_cap",
        dedup_exact=False,
        priority_ids=priority_ids,
    )
