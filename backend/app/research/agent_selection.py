"""Chọn tác tử theo ý nghĩa cho bộ "work" (đợt 5, 19/11, nhóm đã đồng ý).

So ý nghĩa câu hỏi với đoạn mô tả từng tác tử bằng cùng mô hình nhúng đang dùng cho tài liệu; từ khóa vẫn cộng điểm.
Giữ tối đa 3 tác tử chuyên môn + Chuyên viên tổng hợp (≤ 4). Không chắc (điểm sát nhau, không có từ khóa) thì
chỉ giao Chuyên viên tổng hợp, không đoán. Không gọi mô hình sinh, chỉ phép so sánh nên đo được, tái lập được.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Callable

from app.research.decomposer import _contains_hint
from app.research.registry import OFFICE_PACK, PACKS, WORK_PACK

SELECTION_VERSION = "work-agent-selection-v1"
KEYWORD_BONUS = 0.06      # mỗi từ khóa khớp (tối đa 2)
KEEP_WITHIN = 0.04        # giữ tác tử có điểm cách tác tử đầu không quá ngưỡng này
MIN_MARGIN = 0.012        # đầu và nhì sát hơn ngưỡng này mà không có từ khóa → mơ hồ
# Bộ office, câu không khớp từ khóa nào (đo 23/11 trên office-eval-v1 + 12 câu phổ thông): câu tiếng Anh có cosine 0,38–0,42,
# câu ngoài ngành cách nhau 0,01–0,02; câu đúng ngành không từ khóa thì tách rõ (0,066).
OFFICE_MIN_SEM = 0.60
OFFICE_NOHIT_MARGIN = 0.03
MAX_SPECIALISTS = 3

# Mô tả tiếng Việt cho phép so ý nghĩa (câu hỏi người dùng chủ yếu là tiếng Việt).
DESCRIPTIONS = {
    "conditions": "Xét điều kiện: một người hay một trường hợp có được hưởng, có đủ điều kiện, có đạt ngưỡng theo quy định không; tiêu chuẩn, mức tối thiểu, tối đa, ngoại lệ.",
    "procedure": "Quy trình và phê duyệt: các bước làm thủ tục, ai thực hiện, ai duyệt, cấp duyệt, thời hạn, hồ sơ và giấy tờ cần nộp.",
    "terms": "Điều khoản và cam kết: hợp đồng, quyền và nghĩa vụ các bên, điều khoản phạt, bồi thường, chấm dứt, tranh chấp.",
    "figures": "Số liệu và tính toán: bao nhiêu tiền, bao nhiêu ngày, tỷ lệ phần trăm, công thức, tính lương, phép năm, điểm trung bình, bảng số liệu.",
}
# Bộ "office" (văn phòng 3D, 23/11): mô tả theo ngành để so ý nghĩa.
OFFICE_DESCRIPTIONS = {
    "software": "Phần mềm và công nghệ thông tin: yêu cầu hệ thống, thiết kế, API, cơ sở dữ liệu, bảo mật, mã nguồn, máy chủ.",
    "business": "Kinh doanh: mô hình kinh doanh, kế hoạch hoạt động, bán hàng, đối tác, hợp đồng thương mại, chiến lược phát triển.",
    "marketing": "Marketing: nghiên cứu thị trường, khách hàng mục tiêu, chiến dịch quảng cáo, thương hiệu, truyền thông, hiệu quả quảng cáo.",
    "hr": "Nhân sự: tuyển dụng, hợp đồng lao động, nghỉ phép, chế độ lương thưởng, kỷ luật, đánh giá nhân viên, nội quy công ty.",
    "finance": "Tài chính kế toán: ngân sách, chi phí, doanh thu, hóa đơn, thuế, công tác phí, tạm ứng, báo cáo tài chính.",
    "education": "Giáo dục và nghiên cứu: quy chế học vụ, tín chỉ, điểm, học bổng, tốt nghiệp, khóa luận, bài báo khoa học, tài liệu học tập.",
    "analyst": "Phân tích số liệu: tính ra con số, bao nhiêu, tỷ lệ phần trăm, so sánh các con số, xu hướng trong bảng số liệu.",
}
PACK_DESCRIPTIONS = {WORK_PACK: DESCRIPTIONS, OFFICE_PACK: OFFICE_DESCRIPTIONS}


def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


_EMBED_CACHE: dict[tuple[str, str], tuple[float, ...]] = {}
_EMBED_CACHE_MAX = 4096


def _cached(_unused: int, text: str, embed: Callable[[str], tuple[float, ...]]):
    """Vector của mô tả tác tử và câu ví dụ, nhớ theo (mô hình nhúng, chữ). Khóa cũ dùng id() của phương thức gắn với
    đối tượng, mỗi lần truy cập một khác nên gần như luôn trượt (phát hiện 20/11 khi đo Đợt 8)."""
    owner = getattr(embed, "__self__", None)
    key = (str(getattr(owner, "version", None) or id(owner or embed)), text)
    hit = _EMBED_CACHE.get(key)
    if hit is None:
        if len(_EMBED_CACHE) >= _EMBED_CACHE_MAX:
            _EMBED_CACHE.clear()  # shortcut: xóa cả bộ nhớ khi đầy; đủ cho vài nghìn câu ví dụ, đổi sang LRU nếu kho ví dụ lớn hơn
        hit = _EMBED_CACHE[key] = embed(text)
    return hit


def keyword_hits(query: str, pack: str = WORK_PACK) -> dict[str, int]:
    text = query.casefold()
    hints = PACKS[pack]["hints"]
    return {a: sum(1 for h in hints[a] if _contains_hint(text, h)) for a in PACK_DESCRIPTIONS[pack]}


# Đợt 8 (P1-5): học từ người dùng. Ví dụ = câu hỏi người dùng đã chọn cách hiểu (bấm nút hỏi lại, chọn lại tác tử).
# Câu mới giống một ví dụ (cosine ≥ EXAMPLE_SIM) được cộng điểm cho tác tử của ví dụ đó. Chỉ bộ "work" của ô chat
# sản phẩm dùng; thực nghiệm A/B/C không đi qua bộ chọn này nên không đổi.
EXAMPLE_SIM = 0.90  # đo 20/11: câu khác nhau trong agent-routing-v1 vẫn giống nhau 0,80–0,83; chỉ câu gần như hỏi lại mới tính
EXAMPLE_BONUS = 0.08
LEARNED_VERSION = "work-agent-selection-v2-examples"


def select_agents(query: str, embed: Callable[[str], tuple[float, ...]] | None = None,
                  examples: list[tuple[str, str]] | None = None, pack: str = WORK_PACK) -> dict:
    """Trả {"agents": [...chuyên môn..., "general"], "primary", "scores", "ambiguous", "method"}.
    examples: [(câu hỏi, tác tử)] người dùng đã chọn; cần embed để so ý nghĩa, không có thì bỏ qua."""
    descriptions = PACK_DESCRIPTIONS[pack]
    hits = keyword_hits(query, pack)
    sem: dict[str, float] = {}
    learned: dict[str, float] = {}
    if embed is not None:
        q = embed(query)
        sem = {a: _cos(q, _cached(id(embed), d, embed)) for a, d in descriptions.items()}
        for text, agent in examples or []:
            if agent in descriptions:
                sim = _cos(q, _cached(id(embed), text, embed))
                if sim >= EXAMPLE_SIM and sim > learned.get(agent, 0.0):
                    learned[agent] = round(sim, 4)
    scores = {a: round(sem.get(a, 0.0) + KEYWORD_BONUS * min(2, hits[a]) + (EXAMPLE_BONUS if a in learned else 0.0), 4) for a in descriptions}
    ranked = sorted(scores, key=lambda a: (-scores[a], a))
    top, second = ranked[0], ranked[1]
    no_signal = not sem and not any(hits.values())
    ambiguous = no_signal or (scores[top] - scores[second] < MIN_MARGIN and hits[top] == 0 and top not in learned)
    if pack == OFFICE_PACK and sem and not any(hits.values()) and (
            sem[top] < OFFICE_MIN_SEM or scores[top] - scores[second] < OFFICE_NOHIT_MARGIN):
        ambiguous = True  # 23/11: câu ngoài ngành ("thủ đô của Úc", câu tiếng Anh) không khớp từ khóa nào: giao Tổng hợp, không đoán
    if pack == OFFICE_PACK and ambiguous and not no_signal and any(hits.values()):
        ambiguous = False  # Đợt 8: có chuyên gia khớp từ khóa ("khoản chi" → Tài chính) thì giao, không đẩy hết cho Tổng hợp
    if ambiguous:
        chosen: list[str] = []
    else:
        chosen = [a for a in ranked if scores[top] - scores[a] <= KEEP_WITHIN or hits[a] > 0]
        if pack == OFFICE_PACK:
            # Đợt 8: chuyên gia có từ khóa khớp được giữ chỗ trước (vòng 1: "chiến dịch" khớp Marketing nhưng bị đẩy ra khỏi 3 chỗ)
            chosen.sort(key=lambda a: (-min(2, hits[a]), -scores[a], a))
        chosen = chosen[:MAX_SPECIALISTS]
    return {
        "agents": chosen + ["general"],
        "primary": chosen[0] if chosen else "general",
        "scores": scores,
        "keyword_hits": hits,
        "ambiguous": ambiguous,
        "method": "semantic+keyword" if embed is not None else "keyword",
        "version": LEARNED_VERSION if learned else SELECTION_VERSION,
        "learned_from": learned,  # tác tử → độ giống với ví dụ người dùng đã chọn (rỗng = không dùng ví dụ)
        "pack": pack,
    }


__all__ = ["EXAMPLE_BONUS", "EXAMPLE_SIM", "LEARNED_VERSION", "CLARIFY_LABELS", "DESCRIPTIONS", "OFFICE_DESCRIPTIONS", "PACK_CLARIFY",
           "PACK_DESCRIPTIONS", "SELECTION_VERSION", "clarify_options", "forced_selection", "keyword_hits", "select_agents"]


# Hỏi lại khi mơ hồ (mục 3.4): hai cách hiểu sát nhau thì hỏi một câu ngắn kèm 2 nút thay vì đoán.
CLARIFY_LABELS = {
    "conditions": "xét điều kiện (ai được gì, đủ điều kiện không)",
    "procedure": "các bước làm và cấp duyệt",
    "terms": "điều khoản, quyền và nghĩa vụ",
    "figures": "tính số liệu (bao nhiêu, tỷ lệ)",
}
PACK_CLARIFY = {
    WORK_PACK: CLARIFY_LABELS,
    OFFICE_PACK: {
        "software": "phần mềm, hệ thống", "business": "kinh doanh, chiến lược", "marketing": "marketing, quảng cáo",
        "hr": "nhân sự, nội quy", "finance": "tài chính, kế toán", "education": "học tập, nghiên cứu", "analyst": "tính số liệu",
    },
}
CLARIFY_MIN_WORDS = 5  # câu quá ngắn ("Xin chào") không hỏi lại, giao Chuyên viên tổng hợp
# Câu tra cứu, liệt kê ("CSDL gồm những bảng nào?", "X là gì?") có một cách hiểu: tìm và trả lời thẳng, không hỏi lại
# (lỗi tìm ra 20/11: câu này bị hỏi "số liệu hay điều khoản").
_LOOKUP = re.compile(r"\b(bao gom|gom|liet ke|danh sach|la gi|nghia la)\b|\bco (nhung|cac)\b.*\bnao\b")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode().lower()


def clarify_options(query: str, selection: dict) -> list[str] | None:
    """Hai tác tử để hỏi lại, hoặc None khi không cần hỏi (không mơ hồ, câu quá ngắn, hay chỉ chọn theo từ khóa)."""
    if not selection.get("ambiguous") or selection.get("method") != "semantic+keyword":
        return None
    if len(query.split()) < CLARIFY_MIN_WORDS:
        return None
    if _LOOKUP.search(_fold(query)) and not any((selection.get("keyword_hits") or {}).values()):
        return None
    scores = selection["scores"]
    return sorted(scores, key=lambda a: (-scores[a], a))[:2]


def forced_selection(agent: str, pack: str = WORK_PACK) -> dict:
    """Người dùng chọn một cách hiểu (bấm nút khi được hỏi lại): chỉ giao tác tử đó + Tổng hợp."""
    if agent not in PACK_DESCRIPTIONS[pack]:
        raise ValueError(f"Unknown work agent: {agent}")
    return {"agents": [agent, "general"], "primary": agent, "scores": {}, "keyword_hits": {}, "ambiguous": False,
            "method": "user_choice", "version": SELECTION_VERSION, "pack": pack}
