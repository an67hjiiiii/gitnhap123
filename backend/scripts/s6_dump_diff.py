"""Dump pure normalized version changes using the application's extractor."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.documents import extract_document
from app.ingestion.version_diff import diff_versions


def main():
    if len(sys.argv) != 4:
        raise SystemExit("Usage: s6_dump_diff.py <old.txt|docx> <new.txt|docx> <pair>")
    os.environ["VERSION_DIFF"] = "1"
    os.environ.setdefault("INGEST_CLEAN", "rules")
    old, new = [extract_document(Path(p).read_bytes(), Path(p).name).text for p in sys.argv[1:3]]
    print(json.dumps(diff_versions(old, new, sys.argv[3]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
