"""Chấm mù nhiều người: người chấm chỉ thấy câu hỏi, câu trả lời và các ý cần có; không thấy điều kiện (A/B/C...).

- Mỗi câu trả lời thành một mục có mã ngẫu nhiên; điều kiện chỉ lưu phía máy chủ, không gửi cho người chấm.
- Thứ tự mục xáo riêng cho từng người chấm (cố định theo mã người chấm) để giảm thiên lệch thứ tự.
- Tiêu chí: từng ý chính có/không (người kiểm lại chỉ số tự động), Đúng / Đủ / Có căn cứ / Hữu ích (1–5),
  có thông tin sai hoặc bịa (có/không).
- Tổng hợp: trung bình theo điều kiện, so sánh cặp theo câu hỏi (Wilcoxon, Cohen dz), độ đồng thuận giữa người chấm
  (Krippendorff alpha thang khoảng), mức khớp giữa người chấm và chỉ số ý chính tự động.
"""

from __future__ import annotations

import hashlib
import random
import secrets
import string
from statistics import mean

from app.analysis.evaluation import compare_paired, describe

LIKERT = ("correct", "complete", "grounded", "useful")
LABELS = {"correct": "Đúng", "complete": "Đủ ý", "grounded": "Có căn cứ", "useful": "Hữu ích"}


def new_code() -> str:
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def build_items(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """rows: {run_id, condition, question, answer, status, key_points, auto_hits}. Trả (mục chấm, lượt thất bại)."""
    items, failed = [], []
    for r in rows:
        if r.get("status") == "FAILED" or not str(r.get("answer") or "").strip():
            failed.append({"run_id": r["run_id"], "condition": r["condition"], "question": r["question"]})
            continue
        items.append({"item_id": secrets.token_hex(6), "run_id": r["run_id"], "condition": r["condition"],
                      "question": r["question"], "answer": r["answer"], "key_points": list(r.get("key_points") or []),
                      "auto_hits": r.get("auto_hits")})
    return items, failed


def rater_view(items: list[dict], rater_id: str, study_id: str) -> list[dict]:
    """Mục cho người chấm: bỏ điều kiện, mã lượt chạy, điểm tự động; xáo thứ tự theo người chấm."""
    seed = int(hashlib.sha256(f"{study_id}:{rater_id}".encode()).hexdigest()[:12], 16)
    order = list(items)
    random.Random(seed).shuffle(order)
    return [{"item_id": it["item_id"], "question": it["question"], "answer": it["answer"], "key_points": it["key_points"]} for it in order]


def validate_score(score: dict, n_points: int) -> dict:
    kp = score.get("key_points") or []
    if len(kp) != n_points or not all(isinstance(x, bool) for x in kp):
        raise ValueError(f"Cần đánh dấu có/không cho đủ {n_points} ý chính.")
    out = {"key_points": kp, "fabricated": bool(score.get("fabricated"))}
    for k in LIKERT:
        v = score.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5:
            raise ValueError(f"Tiêu chí {LABELS[k]} cần điểm từ 1 đến 5.")
        out[k] = v
    return out


def krippendorff_interval(units: list[list[float]]) -> float | None:
    """Alpha khoảng cho dữ liệu nhiều người chấm, cho phép thiếu; units = danh sách điểm của từng mục."""
    pairable = [u for u in units if len(u) >= 2]
    values = [v for u in pairable for v in u]
    n = len(values)
    if n < 2:
        return None
    d_o = sum(sum((a - b) ** 2 for i, a in enumerate(u) for j, b in enumerate(u) if i != j) / (len(u) - 1) for u in pairable) / n
    d_e = sum((a - b) ** 2 for i, a in enumerate(values) for j, b in enumerate(values) if i != j) / (n * (n - 1))
    return None if d_e == 0 else 1 - d_o / d_e


def aggregate(items: list[dict], failed: list[dict], ratings: list[dict]) -> dict:
    """ratings: {item_id, rater, scores}. Điểm một mục = trung bình các người chấm."""
    by_item: dict[str, list[dict]] = {}
    for r in ratings:
        by_item.setdefault(r["item_id"], []).append(r)
    raters = sorted({r["rater"] for r in ratings})
    per_item = {}
    for it in items:
        rs = by_item.get(it["item_id"], [])
        if not rs:
            continue
        kp = [mean(1.0 if x else 0.0 for x in r["scores"]["key_points"]) if r["scores"]["key_points"] else 0.0 for r in rs]
        overall = [mean(r["scores"][k] for k in LIKERT) for r in rs]
        per_item[it["item_id"]] = {
            "condition": it["condition"], "question": it["question"], "raters": len(rs),
            "kp_coverage": mean(kp), "overall": mean(overall), "fabricated": mean(1.0 if r["scores"]["fabricated"] else 0.0 for r in rs),
            **{k: mean(r["scores"][k] for r in rs) for k in LIKERT},
        }
    conditions = sorted({it["condition"] for it in items} | {f["condition"] for f in failed})
    table = {}
    for c in conditions:
        rows = [v for v in per_item.values() if v["condition"] == c]
        table[c] = {"rated_items": len(rows), "failed_runs": sum(f["condition"] == c for f in failed),
                    "kp_coverage": describe([r["kp_coverage"] for r in rows]), "overall": describe([r["overall"] for r in rows]),
                    "fabricated_rate": mean(r["fabricated"] for r in rows) if rows else None,
                    **{k: describe([r[k] for r in rows])["mean"] for k in LIKERT}}
    # so sánh cặp theo câu hỏi: lượt thất bại tính 0 độ phủ / 1 điểm tổng (trải nghiệm thật của người dùng)
    questions = sorted({it["question"] for it in items} | {f["question"] for f in failed})
    score_of: dict[tuple[str, str], tuple[float, float]] = {}
    for v in per_item.values():
        score_of[(v["question"], v["condition"])] = (v["kp_coverage"], v["overall"])
    for f in failed:
        score_of.setdefault((f["question"], f["condition"]), (0.0, 1.0))
    comparisons = {}
    if "C" in conditions:
        for other in [c for c in conditions if c != "C"]:
            for idx, name in ((0, "kp_coverage"), (1, "overall")):
                xs = [score_of.get((q, "C"), (None, None))[idx] for q in questions]
                ys = [score_of.get((q, other), (None, None))[idx] for q in questions]
                comparisons[f"C_vs_{other}_{name}"] = compare_paired(xs, ys)
    agreement = {}
    for k in (*LIKERT, "kp_coverage"):
        units = []
        for it in items:
            rs = by_item.get(it["item_id"], [])
            vals = [(mean(1.0 if x else 0.0 for x in r["scores"]["key_points"]) if r["scores"]["key_points"] else 0.0) if k == "kp_coverage" else float(r["scores"][k]) for r in rs]
            if vals:
                units.append(vals)
        agreement[k] = krippendorff_interval(units)
    # người chấm so với chỉ số tự động (từng ý chính)
    agree = total = 0
    for it in items:
        auto = it.get("auto_hits")
        if not auto:
            continue
        for r in by_item.get(it["item_id"], []):
            for a, h in zip(auto, r["scores"]["key_points"]):
                total += 1
                agree += int(bool(a) == bool(h))
    return {"raters": raters, "items": len(items), "rated_items": len(per_item), "failed_runs": len(failed),
            "conditions": table, "comparisons": comparisons, "agreement_alpha": agreement,
            "auto_vs_human_agreement": (agree / total) if total else None,
            "ratings_per_rater": {r: sum(1 for x in ratings if x["rater"] == r) for r in raters}}
