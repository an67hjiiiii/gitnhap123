from __future__ import annotations

from pathlib import Path


def test_no_production_module_defines_not_supported_verdict_or_placeholder():
    backend = Path(__file__).resolve().parents[1]
    matches = []
    for root in (backend / "app", backend / "tests"):
        for path in root.rglob("*.py"):
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "NOT_SUPPORTED" in line:
                    matches.append((path.relative_to(backend).as_posix(), line_no, line.strip()))

    production_matches = [item for item in matches if item[0].startswith("app/")]
    assert production_matches == []
