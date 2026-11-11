"""Bộ chạy thực nghiệm (R3 của C1SE.27, viết lại cho API /api/chat của CAP1).

Chạy từng câu hỏi trong bộ dữ liệu dưới nhiều điều kiện (A, B, C, C-P, C-N, C-O), lặp lại N lần,
ghi mỗi lượt một dòng JSONL kèm số đo thật và lưu vết nguồn gốc. Không chấm chất lượng.

Ví dụ:
  set RUNNER_EMAIL=... & set RUNNER_PASSWORD=...   (tài khoản nghiên cứu riêng, không ghi vào file)
  python scripts/research/run_conditions.py --conditions A,C --repeats 2 --out runtime-logs/exp-dev-v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "data" / "research" / "dev-v1" / "cases.json"


def login(client: httpx.Client) -> None:
    email, password = os.getenv("RUNNER_EMAIL"), os.getenv("RUNNER_PASSWORD")
    if not email or not password:
        sys.exit("Cần đặt RUNNER_EMAIL và RUNNER_PASSWORD (tài khoản nghiên cứu riêng).")
    r = client.post("/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        sys.exit(f"Đăng nhập thất bại: HTTP {r.status_code}")


def ensure_corpus(client: httpx.Client, cases: list[dict]) -> dict[str, str]:
    """Nạp mỗi source_text thành một nguồn tên <source_id>.md (bỏ qua nguồn đã có cùng tên)."""
    existing = {s.get("source_name"): s.get("source_id") for s in client.get("/sources").json().get("sources", [])}
    ids = {}
    for case in cases:
        name = f"{case['source_id']}.md"
        if name not in existing:
            r = client.post("/sources/text", json={"source_name": name, "text": case["source_text"]})
            r.raise_for_status()
            existing[name] = r.json()["source_id"]
        ids[case["id"]] = existing[name]
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000/api")
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--conditions", default="A,C")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--cases", default="", help="Danh sách id, ví dụ D01,D02 (mặc định: tất cả)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    dataset = Path(args.dataset)
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    conditions = [c.strip().upper() for c in args.conditions.split(",") if c.strip()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"

    client = httpx.Client(base_url=args.api, timeout=1800)
    login(client)
    health = client.get("/health").json()
    allowed = set(health.get("allowed_conditions") or [])
    missing = [c for c in conditions if c not in allowed]
    if missing:
        sys.exit(f"Điều kiện {missing} không có trong profile hiện tại {sorted(allowed)}; đặt IMPLEMENTATION_PROFILE=m2.")
    ensure_corpus(client, cases)

    manifest = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset.relative_to(ROOT).as_posix() if dataset.is_relative_to(ROOT) else str(dataset),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "conditions": conditions, "repeats": args.repeats, "case_ids": [c["id"] for c in cases],
        "health": {k: health.get(k) for k in ("version", "implementation_profile", "config_hash", "default_provider")},
        "purpose": "technical_run_not_quality_benchmark",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    total = len(cases) * len(conditions) * args.repeats
    done = 0
    with results.open("a", encoding="utf-8") as fh:
        for rep in range(1, args.repeats + 1):
            for case in cases:
                for cond in conditions:
                    t = time.perf_counter()
                    try:
                        r = client.post("/chat", json={"message": case["question"], "condition": cond})
                        run = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                        http = r.status_code
                    except httpx.HTTPError as exc:
                        run, http = {"status": "FAILED", "answer": f"{type(exc).__name__}: {exc}"}, None
                    prov = run.get("provenance") or {}
                    row = {
                        "case_id": case["id"], "family": case.get("family"), "condition": cond, "repeat": rep,
                        "http_status": http, "run_id": run.get("run_id"), "status": run.get("status"),
                        "wall_ms": round((time.perf_counter() - t) * 1000), "metrics": run.get("metrics"),
                        "answer": run.get("answer"),
                        "citations": [c for r_ in run.get("task_results") or [] for c in r_.get("citations") or []],
                        "config_hash": run.get("config_hash"),
                        "code_manifest_sha256": (prov.get("code") or {}).get("manifest_sha256"),
                        "model_digest": (prov.get("model") or {}).get("digest"),
                        "context_policy": prov.get("context_policy"),
                        "embedding_version": prov.get("embedding_version"),
                    }
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    done += 1
                    print(f"[{done}/{total}] {case['id']} {cond} r{rep}: {row['status']} {row['wall_ms']} ms", flush=True)


if __name__ == "__main__":
    main()
