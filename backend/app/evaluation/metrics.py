"""Count-based metrics. Rows are independent labelled requirements, not repeats."""

LABELS = ("SATISFIED", "PARTIAL", "DEVIATES", "NOT_FOUND")
NOTE = "raw counts only; no significance claims on n<30"


def _rate(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else 0.0}


def score(rows: list[dict]) -> dict:
    """Confusion rows are expected labels, columns predicted (including abstentions).

    Evidence hit means ANY expected locator exactly matches a cited locator.
    Requirements with no expected locator are excluded from that denominator.
    False-DEVIATES uses all expected non-DEVIATES as its denominator.
    Undefined rates are zero with an explicit zero denominator.
    """
    for row in rows:
        if row["expected"] not in LABELS:
            raise ValueError("Unsupported expected verdict")
        if row["predicted"] not in (*LABELS, "UNDETERMINED", "SKIPPED_BUDGET"):
            raise ValueError("Unsupported predicted verdict")
    columns = [*LABELS, *sorted({r["predicted"] for r in rows} - set(LABELS))]
    matrix = {label: dict.fromkeys(columns, 0) for label in LABELS}
    for row in rows:
        matrix[row["expected"]][row["predicted"]] += 1
    per_verdict = {}
    for label in LABELS:
        tp = matrix[label][label]
        fp = sum(r["predicted"] == label and r["expected"] != label for r in rows)
        fn = sum(r["expected"] == label and r["predicted"] != label for r in rows)
        per_verdict[label] = {"tp": tp, "fp": fp, "fn": fn, "support": tp + fn,
                              "precision": _rate(tp, tp + fp), "recall": _rate(tp, tp + fn),
                              "f1": _rate(2 * tp, 2 * tp + fp + fn)}
    eligible = [r for r in rows if r.get("expected_locators")]
    hits = sum(bool(set(r["expected_locators"]) & set(r["cited_locators"])) for r in eligible)
    return {
        "n": len(rows), "note": NOTE, "per_verdict": per_verdict,
        "macro_f1": {"rate": sum(v["f1"]["rate"] for v in per_verdict.values()) / len(LABELS),
                     "label_count": len(LABELS), "n": len(rows)},
        "exact_match_accuracy": _rate(sum(r["expected"] == r["predicted"] for r in rows), len(rows)),
        "confusion_matrix": matrix,
        "evidence_hit_rate": _rate(hits, len(eligible)),
        "false_deviates_rate": _rate(
            sum(r["predicted"] == "DEVIATES" and r["expected"] != "DEVIATES" for r in rows),
            sum(r["expected"] != "DEVIATES" for r in rows)),
    }
