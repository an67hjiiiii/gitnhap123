"""Chọn tác tử theo ý nghĩa cho bộ "work" (đợt 5, 19/11, nhóm đã đồng ý).

So ý nghĩa câu hỏi với đoạn mô tả từng tác tử bằng cùng mô hình nhúng đang dùng cho tài liệu; từ khóa vẫn cộng điểm.
Giữ tối đa 3 tác tử chuyên môn + Chuyên viên tổng hợp (≤ 4). Không chắc (điểm sát nhau, không có từ khóa) thì
chỉ giao Chuyên viên tổng hợp, không đoán. Không gọi mô hình sinh, chỉ phép so sánh nên đo được, tái lập được.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Callable

from app.research.decomposer import _contains_hint
from app.research.registry import PACKS, WORK_PACK

SELECTION_VERSION = "work-agent-selection-v1"
KEYWORD_BONUS = 0.06      # mỗi từ khóa khớp (tối đa 2)
KEEP_WITHIN = 0.04        # giữ tác tử có điểm cách tác tử đầu không quá ngưỡng này
MIN_MARGIN = 0.012        # đầu và nhì sát hơn ngưỡng này mà không có từ khóa → mơ hồ
MAX_SPECIALISTS = 3

# Mô tả tiếng Việt cho phép so ý nghĩa (câu hỏi người dùng chủ yếu là tiếng Việt).
DESCRIPTIONS = {
    "conditions": "Xét điều kiện: một người hay một trường hợp có được hưởng, có đủ điều kiện, có đạt ngưỡng theo quy định không; tiêu chuẩn, mức tối thiểu, tối đa, ngoại lệ.",
    "procedure": "Quy trình và phê duyệt: các bước làm thủ tục, ai thực hiện, ai duyệt, cấp duyệt, thời hạn, hồ sơ và giấy tờ cần nộp.",
    "terms": "Điều khoản và cam kết: hợp đồng, quyền và nghĩa vụ các bên, điều khoản phạt, bồi thường, chấm dứt, tranh chấp.",
    "figures": "Số liệu và tính toán: bao nhiêu tiền, bao nhiêu ngày, tỷ lệ phần trăm, công thức, tính lương, phép năm, điểm trung bình, bảng số liệu.",
}


def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


@lru_cache(maxsize=64)
def _cached(embed_id: int, text: str, embed: Callable[[str], tuple[float, ...]]):
    return embed(text)


def keyword_hits(query: str) -> dict[str, int]:
    text = query.casefold()
    hints = PACKS[WORK_PACK]["hints"]
    return {a: sum(1 for h in hints[a] if _contains_hint(text, h)) for a in DESCRIPTIONS}


def select_agents(query: str, embed: Callable[[str], tuple[float, ...]] | None = None) -> dict:
    """Trả {"agents": [...chuyên môn..., "general"], "primary", "scores", "ambiguous", "method"}."""
    hits = keyword_hits(query)
    sem: dict[str, float] = {}
    if embed is not None:
        q = embed(query)
        sem = {a: _cos(q, _cached(id(embed), d, embed)) for a, d in DESCRIPTIONS.items()}
    scores = {a: round(sem.get(a, 0.0) + KEYWORD_BONUS * min(2, hits[a]), 4) for a in DESCRIPTIONS}
    ranked = sorted(scores, key=lambda a: (-scores[a], a))
    top, second = ranked[0], ranked[1]
    no_signal = not sem and not any(hits.values())
    ambiguous = no_signal or (scores[top] - scores[second] < MIN_MARGIN and hits[top] == 0)
    if ambiguous:
        chosen: list[str] = []
    else:
        chosen = [a for a in ranked if scores[top] - scores[a] <= KEEP_WITHIN or hits[a] > 0][:MAX_SPECIALISTS]
    return {
        "agents": chosen + ["general"],
        "primary": chosen[0] if chosen else "general",
        "scores": scores,
        "keyword_hits": hits,
        "ambiguous": ambiguous,
        "method": "semantic+keyword" if embed is not None else "keyword",
        "version": SELECTION_VERSION,
    }


__all__ = ["CLARIFY_LABELS", "DESCRIPTIONS", "SELECTION_VERSION", "clarify_options", "forced_selection", "keyword_hits", "select_agents"]


# Hỏi lại khi mơ hồ (mục 3.4): hai cách hiểu sát nhau thì hỏi một câu ngắn kèm 2 nút thay vì đoán.
CLARIFY_LABELS = {
    "conditions": "xét điều kiện (ai được gì, đủ điều kiện không)",
    "procedure": "các bước làm và cấp duyệt",
    "terms": "điều khoản, quyền và nghĩa vụ",
    "figures": "tính số liệu (bao nhiêu, tỷ lệ)",
}
CLARIFY_MIN_WORDS = 5  # câu quá ngắn ("Xin chào") không hỏi lại, giao Chuyên viên tổng hợp


def clarify_options(query: str, selection: dict) -> list[str] | None:
    """Hai tác tử để hỏi lại, hoặc None khi không cần hỏi (không mơ hồ, câu quá ngắn, hay chỉ chọn theo từ khóa)."""
    if not selection.get("ambiguous") or selection.get("method") != "semantic+keyword":
        return None
    if len(query.split()) < CLARIFY_MIN_WORDS:
        return None
    scores = selection["scores"]
    return sorted(scores, key=lambda a: (-scores[a], a))[:2]


def forced_selection(agent: str) -> dict:
    """Người dùng chọn một cách hiểu (bấm nút khi được hỏi lại): chỉ giao tác tử đó + Tổng hợp."""
    if agent not in DESCRIPTIONS:
        raise ValueError(f"Unknown work agent: {agent}")
    return {"agents": [agent, "general"], "primary": agent, "scores": {}, "keyword_hits": {}, "ambiguous": False,
            "method": "user_choice", "version": SELECTION_VERSION}
