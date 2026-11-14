"""Opt-in real-model experiment. Run from backend; dry-run needs no services."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import subprocess
import sys

# Do not load repository .env files or write bytecode when importing the app.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.real_runner import (
    authorize, mark_watchdog_timeout, run_experiment, validate_limits,
    validate_output, validate_qdrant_dir,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--baseline-only", action="store_true",
                        help="Run only the six direct, source-free baseline calls")
    parser.add_argument("--max-invocations", type=int, default=24)
    parser.add_argument("--max-minutes", type=float, default=60)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--qdrant-dir", type=Path)
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        authorize(real=args.real, dry_run=args.dry_run)
        validate_limits(args.max_invocations, args.max_minutes)
        validate_output(args.out)
        if args.qdrant_dir is not None:
            validate_qdrant_dir(args.qdrant_dir)
        elif not args.baseline_only:
            raise ValueError("Real experiments require qdrant-dir")
    except (ValueError, PermissionError) as exc:
        parser.error(str(exc))
    if args._worker:
        result = asyncio.run(run_experiment(
            out=args.out, qdrant_dir=args.qdrant_dir, real=args.real, dry_run=args.dry_run,
            max_invocations=args.max_invocations, max_minutes=args.max_minutes,
            baseline_only=args.baseline_only))
        print(f"partial={result['partial']} calls={result['total_calls']} out={args.out}")
        return 2 if result["partial"] else 0
    # One inference process, no threads. The parent kills even synchronous hangs.
    arguments = list(sys.argv[1:] if argv is None else argv)
    worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *arguments, "--_worker"],
                              stdin=subprocess.DEVNULL)
    try:
        return worker.wait(timeout=args.max_minutes * 60)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait()
        mark_watchdog_timeout(args.out, seconds=args.max_minutes * 60,
                             dry_run=args.dry_run, max_invocations=args.max_invocations)
        return 2
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait()


if __name__ == "__main__":
    raise SystemExit(main())
