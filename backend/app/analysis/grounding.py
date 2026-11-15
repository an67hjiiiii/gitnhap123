"""Đèn báo độ tin cậy: đối chiếu từng câu của câu trả lời với các đoạn tài liệu mà lượt chạy đã đọc.

Cách làm nhẹ, chạy tại máy, không gọi mô hình: mỗi câu tìm đoạn có tỷ lệ từ nội dung trùng cao nhất; con số trong câu
phải có trong đoạn đó. Đánh giá theo từng câu để một câu thiếu căn cứ không bị che bởi điểm trung bình. Giới hạn: đối
chiếu theo từ ngữ nên câu diễn đạt lại có thể bị đánh "cần kiểm tra"; vì vậy mức thấp nhất là "chưa thấy căn cứ", không
kết luận là sai.
"""

from __future__ import annotations

import re

from app.analysis.evaluation import _content_tokens
from app.analysis.traceability import _numbers
from app.core.types import SourceChunk

SUPPORTED, WEAK = 0.6, 0.35
_CHUNK_REF = re.compile(r"\(?(?:chunk(?:_id)?:?\s*)?\[?src_[0-9a-f]+_c\d+\]?\)?", re.I)


def answer_sentences(answer: str) -> list[str]:
    """Câu có nội dung của câu trả lời: bỏ dòng "Nguồn:", mã đoạn, đề mục rỗng; câu dưới 3 từ nội dung bị bỏ qua."""
    text = re.sub(r"\n\s*Nguồn:.*$", "", answer.strip(), flags=re.S)
    text = _CHUNK_REF.sub("", text)
    parts = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*+•]|\d+[.)])\s*", "", line).strip()
        parts += [s.strip() for s in re.split(r"(?<=[.!?;])\s+", line) if s.strip()]
    return [p for p in parts if len(_content_tokens(p)) >= 3]


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:]))


def ground_answer(answer: str, chunks: list[SourceChunk]) -> dict:
    prepared = [(c, set(_content_tokens(c.text)), _bigrams(_content_tokens(c.text)), _numbers(c.text)) for c in chunks]
    rows = []
    for sentence in answer_sentences(answer):
        tokens = _content_tokens(sentence)
        words, pairs, nums = set(tokens), _bigrams(tokens), _numbers(sentence)
        best = None
        for chunk, cw, cb, _cn in prepared:
            # trùng từ đơn là chính, trùng cặp từ (giữ thứ tự) cộng thêm để ưu tiên đoạn nói đúng cụm đó
            score = 0.7 * len(words & cw) / len(words) + 0.3 * (len(pairs & cb) / len(pairs) if pairs else 0)
            if best is None or score > best[1]:
                best = (chunk, score)
        chunk, score = best if best else (None, 0.0)
        missing_numbers = sorted(nums - next((cn for c, _w, _b, cn in prepared if c is chunk), set())) if chunk else sorted(nums)
        level = "supported" if score >= SUPPORTED and not missing_numbers else "weak" if score >= WEAK else "unsupported"
        rows.append({"text": sentence, "level": level, "score": round(score, 3), "missing_numbers": missing_numbers,
                     "chunk_id": chunk.chunk_id if chunk else None, "source_name": chunk.source_name if chunk else None})
    counts = {lv: sum(r["level"] == lv for r in rows) for lv in ("supported", "weak", "unsupported")}
    return {"sentences": rows, "counts": counts, "evidence_chunks": len(chunks)}


def run_evidence_ids(run: dict) -> list[str]:
    """Mã các đoạn lượt chạy đã đưa cho mô hình (retrieval của A, của từng nhiệm vụ B/C) cộng trích dẫn."""
    ids: list[str] = []
    for event in run.get("events") or []:
        if event.get("stage") in ("vanilla_retrieval", "task_retrieval"):
            ids += [str(x) for x in event.get("selected") or []]
    for result in run.get("task_results") or []:
        ids += [str(x) for x in result.get("citations") or []]
    return list(dict.fromkeys(i for i in ids if i))
