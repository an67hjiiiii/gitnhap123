"""Run the guarded experiment matrix offline by default."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.experiment import fake_registry, load_config, load_experiment_corpus, run_experiment
from app.evaluation.guard import ResourceGuard, ResourceGuardError
from app.evaluation.report import markdown, write_report


def main(argv=None, *, registry=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Default: fake engines only")
    mode.add_argument("--real", action="store_true", help="Requires REVIEW_EXPERIMENT_ALLOW_REAL=1")
    parser.add_argument("--max-inferences", type=int, default=1000)
    parser.add_argument("--per-run-timeout", type=float, default=30)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] /
                        "tests" / "fixtures" / "experiment" / "experiment.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        out = args.out.resolve()
        repo = Path(__file__).resolve().parents[2]
        if any(path == out or path in out.parents for path in (repo / "data", repo / "backend" / "data")):
            raise ValueError("Refusing to write inside repository data/ directory")
        with ResourceGuard(args.max_inferences, args.per_run_timeout, real=args.real) as guard:
            if args.real:
                guard.authorize(is_fake=False)
            config = load_config(args.config)
            corpus = load_experiment_corpus(config, args.config.parent)
            result = run_experiment(config, corpus, fake_registry() if registry is None else registry,
                                    guard, dry_run=not args.real)
        write_report(result, out)
    except (ValueError, KeyError, ResourceGuardError) as exc:
        parser.error(str(exc))
    print(f"partial={result.results['partial']}; inferences={result.results['inferences']}; "
          f"stop_reason={result.results['stop_reason']}")
    print(markdown(result))
    return 1 if result.results["partial"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
