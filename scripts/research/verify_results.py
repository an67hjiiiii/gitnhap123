"""Kiểm tra một thư mục kết quả của run_conditions.py: đủ lượt, có số đo thật, có lưu vết, mã nguồn và
mô hình nhất quán giữa các lượt. In bảng mô tả theo điều kiện (trung vị), không kết luận chất lượng."""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def main(folder: str) -> int:
    out = Path(folder)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    problems = []
    expected = len(manifest["case_ids"]) * len(manifest["conditions"]) * manifest["repeats"]
    if len(rows) != expected:
        problems.append(f"có {len(rows)} lượt, cần {expected}")
    keys = {(r["case_id"], r["condition"], r["repeat"]) for r in rows}
    if len(keys) != len(rows):
        problems.append("có lượt bị trùng (case, điều kiện, lần lặp)")
    for field in ("code_manifest_sha256", "model_digest", "config_hash"):
        values = {r.get(field) for r in rows if r.get("status") != "FAILED"}
        if len(values) > 1:
            problems.append(f"{field} thay đổi giữa các lượt: {sorted(map(str, values))}")
        if None in values:
            problems.append(f"thiếu {field} ở lượt không lỗi")
    by_cond = defaultdict(list)
    for r in rows:
        by_cond[r["condition"]].append(r)
    print(f"{'Điều kiện':<10}{'Lượt':>6}{'Lỗi':>6}{'Token (trung vị)':>18}{'Thời gian ms (trung vị)':>26}")
    for cond, items in sorted(by_cond.items()):
        ok = [r for r in items if r.get("status") not in (None, "FAILED")]
        tokens = [(r["metrics"] or {}).get("input_tokens", 0) + (r["metrics"] or {}).get("output_tokens", 0) for r in ok]
        lat = [r["wall_ms"] for r in ok]
        med = lambda xs: statistics.median(xs) if xs else None
        print(f"{cond:<10}{len(items):>6}{len(items) - len(ok):>6}{str(med(tokens)):>18}{str(med(lat)):>26}")
    print("Ghi chú: số mô tả kỹ thuật, chưa chấm chất lượng, không dùng làm kết luận nghiên cứu.")
    if problems:
        print("VẤN ĐỀ:", *problems, sep="\n- ")
        return 1
    print("Kiểm tra cấu trúc: đạt.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
