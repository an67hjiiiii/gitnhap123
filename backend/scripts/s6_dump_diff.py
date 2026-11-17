"""Dump pure normalized version changes using the application's extractor."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.documents import extract_document
from app.ingestion.version_diff import diff_versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("pair")
    parser.add_argument("--with-text", action="store_true")
    args = parser.parse_args()
    os.environ["VERSION_DIFF"] = "1"
    os.environ.setdefault("INGEST_CLEAN", "rules")
    old, new = [extract_document(Path(p).read_bytes(), Path(p).name).text for p in (args.old, args.new)]
    rows = diff_versions(old, new, args.pair, include_text=args.with_text)
    if args.with_text:
        rows = [{**{key: row[key] for key in ("pair", "old_article", "new_article", "kind", "atoms_before", "atoms_after")},
                 "text_before": row["text_before"][:300], "text_after": row["text_after"][:300]} for row in rows]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
