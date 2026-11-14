# Quality baselines (Q-1)
Generated on branch s3/q-1 from s3/integration fd5a0f4 with a SEPARATE dev venv (D:\CAP1-Orchestration\devvenv); the Owner venv was not touched.
- ruff: 93 findings in app/ (ruff-baseline.txt: file:rule:message lines, line numbers stripped). Gate: no NEW line vs baseline.
- mypy: 90 errors in 26 files (mypy-baseline.txt). Gate: no NEW error vs baseline.
- import-linter: 3 contracts kept, 0 broken (pyproject.toml). Gate: all kept.
- coverage: see coverage-summary.txt (branch coverage on app/, full suite 998 passed incl. PG).
- pip-audit: pip-audit-report.txt (only pytest 8.4.2 PYSEC-2026-1845, fix 9.0.3 but requirements pin <9; dev dependency).
Commands (cwd backend, dev venv): python -m ruff check app; python -m mypy app; lint-imports; python -m pytest --cov=app; python -m pip_audit -r requirements.txt