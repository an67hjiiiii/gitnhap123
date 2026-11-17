"""Sample real version changes for manual review; never assign review scores."""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.documents import extract_document
from app.ingestion.version_diff import diff_versions


CORPUS = Path("D:/CAP1-Orchestration/work/legal_corpus")
PAIRS = (("TT08-2022-BGDDT", "06"), ("TT18-2021-BGDDT", "53"), ("TT25-2021-BGDDT", "50"))
FIELDS = ("cap", "trich_cu", "trich_moi", "loai_thay_doi", "dung_sai_nhieu")


def sample_rows(seed: int) -> list[dict]:
    os.environ["VERSION_DIFF"] = "1"
    os.environ.setdefault("INGEST_CLEAN", "rules")
    rng = random.Random(seed)
    result = []
    for old_name, new_number in PAIRS:
        old_path = CORPUS / "old_versions" / (old_name + ".docx")
        matches = []
        for directory in ("clean", "drive_bgd"):
            matches = sorted((CORPUS / directory).glob(f"{new_number}_2026*.txt"))
            if matches:
                break
        if len(matches) != 1:
            raise ValueError(f"Expected one new text for {old_name}, found {matches}")
        new_path = matches[0]
        old, new = [extract_document(p.read_bytes(), p.name).text for p in (old_path, new_path)]
        pair = f"{old_name} -> {new_number}/2026"
        changes = diff_versions(old, new, pair, include_text=True)
        for row in rng.sample(changes, 30):
            result.append(dict(cap=pair, trich_cu=row["text_before"], trich_moi=row["text_after"],
                               loai_thay_doi=row["kind"], dung_sai_nhieu=""))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed", type=int)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    rows = sample_rows(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} data rows: {args.out}")


if __name__ == "__main__":
    main()
