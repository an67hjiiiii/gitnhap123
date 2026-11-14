"""Run offline corpus scoring: python scripts/run_eval.py --out <directory>."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.harness import default_conditions, load_corpus, run
from app.evaluation.report import write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conditions", nargs="+", help="Names separated by spaces or commas")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    available = {c.name: c for c in default_conditions()}
    names = [name for arg in args.conditions for name in arg.split(",")] if args.conditions else list(available)
    if any(name not in available for name in names) or args.repeats < 1 or len(set(names)) != len(names):
        parser.error("Use unique known conditions and positive repeats: " + ", ".join(available))
    corpus = load_corpus(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "eval")
    try:
        write_report(run([available[name] for name in names], corpus, args.repeats, args.seed), args.out)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
