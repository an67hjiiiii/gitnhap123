from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

class RunStore:
    def __init__(self, root: str = "runs"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, run: dict) -> None:
        run_id = run["run_id"]
        (self.root / f"{run_id}.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, run_id: str) -> dict | None:
        path = self.root / f"{run_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def mark_stale_running_runs(self, max_age_seconds: float) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        updated = 0
        for path in self.root.glob("*.json"):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
                created_at = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if (run.get("lifecycle_status") or run.get("status")) != "RUNNING" or created_at >= cutoff:
                continue
            run.update(status="FAILED", lifecycle_status="FAILED", answer="STALE_RUN", error="STALE_RUN")
            self.save(run)
            updated += 1
        return updated

    def list(self, limit: int = 30) -> list[dict]:
        rows: list[dict] = []
        for path in sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                rows.append({
                    k: item.get(k)
                    for k in (
                        "run_id",
                        "created_at",
                        "condition",
                        "query",
                        "status",
                        "lifecycle_status",
                        "metrics",
                    )
                })
            except Exception:
                continue
        return rows
