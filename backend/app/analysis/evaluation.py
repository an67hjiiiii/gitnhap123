"""Phòng đánh giá thực nghiệm: độ phủ ý chính tự động và thống kê so sánh các điều kiện.

Số liệu đầu vào lấy từ lượt chạy thật (độ trễ, token đo bởi Ollama) và điểm chấm của người. Độ phủ ý chính
tự động chỉ dựa trên từ khóa nên là chỉ số phụ, không thay người chấm. Thống kê viết thuần Python để không
thêm thư viện: trung bình, khoảng tin cậy 95% (phân phối t), kiểm định Wilcoxon cặp (chính xác khi n ≤ 30),
cỡ hiệu ứng rank-biserial và Cohen's dz.
"""

from __future__ import annotations

import math
import re
import unicodedata
from statistics import mean, stdev

# Hư từ tiếng Việt và tiếng Anh không mang nội dung khi so ý chính với câu trả lời.
_STOP = set("""
và hoặc của là có được các những một này đó cho với trong khi thì mà để từ theo về như không phải cần sẽ đã đang bị
thể nếu nên vì do tại trên dưới ra vào lại cũng rất nhiều ít mỗi mọi hệ thống
the a an and or of to in on for with by is are be must should can will this that it as at from
""".split())


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").replace("đ", "d")


def _content_tokens(text: str) -> list[str]:
    stop = {_fold(w) for w in _STOP}
    return [t for t in re.findall(r"[a-z0-9]+(?:[.,][0-9]+)*", _fold(text)) if t not in stop]


def keypoint_hits(answer: str, key_points: list[str], threshold: float = 0.6) -> list[bool]:
    """Một ý chính coi là có trong câu trả lời khi ≥ threshold số từ nội dung của ý (bỏ dấu, bỏ hư từ) xuất hiện."""
    have = set(_content_tokens(answer))
    hits = []
    for point in key_points:
        need = set(_content_tokens(point))
        hits.append(bool(need) and len(need & have) / len(need) >= threshold)
    return hits


# ---------------- Thống kê
_T975 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
         2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)


def t_critical(df: int) -> float:
    """Giá trị t hai phía 95%: bảng chuẩn cho df ≤ 30, nội suy theo 1/df tới 1.96 khi df lớn."""
    if df < 1:
        return float("nan")
    if df <= 30:
        return _T975[df - 1]
    anchors = ((30, 2.042), (40, 2.021), (60, 2.000), (120, 1.980), (math.inf, 1.960))
    for (d0, t0), (d1, t1) in zip(anchors, anchors[1:]):
        if df <= d1:
            w = (1 / d0 - 1 / df) / (1 / d0 - (0 if d1 == math.inf else 1 / d1))
            return t0 + (t1 - t0) * w
    return 1.960


def describe(values: list[float]) -> dict:
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "ci95": None}
    m = mean(vals)
    if n == 1:
        return {"n": 1, "mean": m, "sd": None, "ci95": None}
    sd = stdev(vals)
    half = t_critical(n - 1) * sd / math.sqrt(n)
    return {"n": n, "mean": m, "sd": sd, "ci95": [m - half, m + half]}


def _avg_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1  # hạng trung bình cho giá trị bằng nhau
        i = j + 1
    return ranks


def _normal_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def wilcoxon_signed_rank(x: list[float], y: list[float]) -> dict:
    """Kiểm định Wilcoxon cặp hai phía cho x - y. Bỏ cặp chênh lệch 0 (cách của Wilcoxon).

    n ≤ 30: p chính xác bằng quy hoạch động trên tổng hạng (hạng nhân 2 để giữ hạng .5 khi bằng nhau).
    n > 30: xấp xỉ chuẩn có hiệu chỉnh hạng bằng nhau và hiệu chỉnh liên tục.
    """
    if len(x) != len(y):
        raise ValueError("x và y phải cùng số phần tử (dữ liệu cặp)")
    diffs = [a - b for a, b in zip(x, y) if a is not None and b is not None and a != b]
    n = len(diffs)
    if n == 0:
        return {"n": 0, "w_plus": 0.0, "w_minus": 0.0, "p_value": None, "method": "không có cặp khác nhau", "rank_biserial": None}
    ranks = _avg_ranks([abs(d) for d in diffs])
    w_plus = sum(r for r, d in zip(ranks, diffs) if d > 0)
    w_minus = sum(r for r, d in zip(ranks, diffs) if d < 0)
    total = w_plus + w_minus
    rank_biserial = (w_plus - w_minus) / total
    if n <= 30:
        doubled = [int(round(r * 2)) for r in ranks]
        counts = {0: 1}
        for r in doubled:
            nxt = dict(counts)
            for s, c in counts.items():
                nxt[s + r] = nxt.get(s + r, 0) + c
            counts = nxt
        observed = int(round(min(w_plus, w_minus) * 2))
        tail = sum(c for s, c in counts.items() if s <= observed)
        p = min(1.0, 2 * tail / 2 ** n)
        method = "chính xác"
    else:
        mu = n * (n + 1) / 4
        ties: dict[float, int] = {}
        for r in ranks:
            ties[r] = ties.get(r, 0) + 1
        var = n * (n + 1) * (2 * n + 1) / 24 - sum(t ** 3 - t for t in ties.values()) / 48
        z = (abs(w_plus - mu) - 0.5) / math.sqrt(var) if var > 0 else 0.0
        p = _normal_two_sided(z)
        method = "xấp xỉ chuẩn"
    return {"n": n, "w_plus": w_plus, "w_minus": w_minus, "p_value": p, "method": method, "rank_biserial": rank_biserial}


def cohens_dz(x: list[float], y: list[float]) -> float | None:
    diffs = [a - b for a, b in zip(x, y) if a is not None and b is not None]
    if len(diffs) < 2:
        return None
    sd = stdev(diffs)
    return None if sd == 0 else mean(diffs) / sd


def compare_paired(x: list[float], y: list[float]) -> dict:
    """Tóm tắt so sánh cặp (cùng câu hỏi) giữa hai điều kiện."""
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    xs, ys = [a for a, _ in pairs], [b for _, b in pairs]
    return {"pairs": len(pairs), "mean_diff": mean([a - b for a, b in pairs]) if pairs else None,
            "wilcoxon": wilcoxon_signed_rank(xs, ys), "cohens_dz": cohens_dz(xs, ys)}


def readable_answer(raw: object) -> str:
    """Câu trả lời dạng chữ: bộ tổng hợp đôi khi trả chuỗi JSON (answer hoặc task_results[].answer)."""
    from app.core.structured_output import parse_answer_json

    text = str(raw or "").strip()
    if not text.startswith("{"):
        return text
    obj = parse_answer_json(text)
    if isinstance(obj.get("answer"), str) and obj["answer"].strip():
        return obj["answer"].strip()
    parts = [str(r.get("answer")).strip() for r in obj.get("task_results") or [] if isinstance(r, dict) and str(r.get("answer") or "").strip()]
    return "\n\n".join(parts) or text


METRIC_KEYS = ("latency_ms", "input_tokens", "output_tokens", "llm_calls", "citations_emitted", "citations_valid",
               "retrieved_chunks", "selected_chunks", "dropped_chunks", "context_tokens_est", "peak_rss_mb", "gpu_memory_mb",
               "cpu_percent", "model_rss_mb")
