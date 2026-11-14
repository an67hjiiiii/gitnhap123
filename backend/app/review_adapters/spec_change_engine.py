"""Deterministic review adapter for semantic OpenAPI changes."""

from __future__ import annotations

import inspect as pyinspect
import re
from collections.abc import Callable

from app.review.schemas import Confidence, Evidence, Finding, Requirement, ReviewCase, Verdict
from app.review.labels import label
from app.review.tools.openapi_diff import Change, diff
from app.review.tools.openapi_inspect import inspect as inspect_openapi


class SpecChangeEngine:
    """Review requirements against injected old and new OpenAPI documents."""

    def __init__(self, old_doc_loader: Callable[[ReviewCase], str], new_doc_loader: Callable[[ReviewCase], str]) -> None:
        self.old_doc_loader = old_doc_loader
        self.new_doc_loader = new_doc_loader

    def _changes(self, case: ReviewCase) -> list[Change]:
        return diff(self.old_doc_loader(case), self.new_doc_loader(case)).changes

    @staticmethod
    def _evidence(case: ReviewCase, change: Change, index: int) -> Evidence:
        return Evidence(
            evidence_id=f"chg:{index + 1}",
            source_id=(case.old_source_id or "old") if change.severity == "BREAKING" else (case.new_source_id or "new"),
            locator=" ".join(x for x in (change.method.upper(), change.path,
                                         f"[#{change.location}]" if change.location else "") if x),
            excerpt=label("changes", change.kind),
        )

    def evidence(self, case: ReviewCase) -> list[Evidence]:
        """Allowlist deterministic citations derived from the owner-scoped loaders."""
        try:
            return [self._evidence(case, change, index) for index, change in enumerate(self._changes(case))]
        except Exception:
            return []

    def propose_requirements(self, case: ReviewCase) -> list[Requirement]:
        try:
            changes = self._changes(case)
        except Exception:
            return []
        groups: dict[tuple[str, str, str], str] = {}
        try:
            old_ops = inspect_openapi(self.old_doc_loader(case)).operations
            new_ops = inspect_openapi(self.new_doc_loader(case)).operations
        except Exception:
            old_ops, new_ops = [], []
        for change in changes:
            if change.method:
                key = ("operation", change.method.upper(), change.path)
                text = f"Verify consumers of {change.method.upper()} {change.path} after its change"
            elif change.path:
                affected = old_ops if change.severity == "BREAKING" else new_ops
                methods = sorted({op.method.upper() for op in affected if op.path == change.path})
                if not methods:
                    methods = [""]
                for method in methods:
                    key = ("operation" if method else "path", method, change.path)
                    subject = f"{method} {change.path}" if method else change.path
                    groups.setdefault(key, f"Verify consumers of {subject} after its change")
                continue
            else:
                schema = change.location.partition(":")[2].partition(".")[0]
                if not schema:
                    continue
                key = ("schema", "", schema)
                text = f"Verify consumers of schema {schema} after its change"
            groups.setdefault(key, text)
        values = list(groups.values())[:25]
        return [Requirement(id=f"{case.id}:spec-req-{i + 1}", case_id=case.id, text=text,
                            origin="AI_PROPOSED", confirmed=False, order=i)
                for i, text in enumerate(values)]

    @staticmethod
    def _related(requirement: Requirement, changes: list[Change]) -> list[Change]:
        text = requirement.text.casefold()
        method_path = re.search(r"\b(get|put|post|delete|options|head|patch|trace)\s+(/\S*)", text)
        path_match = re.search(r"(/[a-z0-9_{}./~:-]+)", text)
        schema_match = re.search(r"\bschema\s+([a-z0-9_.-]+)", text)
        if method_path:
            method, path = method_path.group(1).upper(), method_path.group(2).rstrip(".,;:)")
            return [c for c in changes if c.path == path and (not c.method or c.method.upper() == method)]
        if schema_match:
            name = schema_match.group(1).split(".")[0]
            return [c for c in changes if c.location.startswith(f"schema:{name}.")]
        if path_match:
            path = path_match.group(1).rstrip(".,;:)")
            return [c for c in changes if c.path == path]
        return []

    @staticmethod
    def _emit(emit: Callable, name: str, payload: dict, finding: Finding | None = None) -> None:
        try:
            pyinspect.signature(emit).bind(name, payload)
        except (TypeError, ValueError):
            if finding is not None:
                emit(finding)
        else:
            emit(name, payload)

    def run(self, case: ReviewCase, requirements: list[Requirement], budget: dict | None,
            emit: Callable) -> list[Finding]:
        budget = budget or {}
        try:
            changes = self._changes(case)
            parse_failed = False
        except Exception:
            changes = []
            parse_failed = True
        limit = budget.get("max_requirements")
        findings: list[Finding] = []
        evaluated = 0
        for requirement in requirements:
            if not requirement.confirmed:
                continue
            base = {"case_id": case.id, "requirement_id": requirement.id}
            if limit is not None and evaluated >= limit:
                verdict, evidence = Verdict.SKIPPED_BUDGET, []
                self._emit(emit, "budget.skipped", base)
            else:
                evaluated += 1
                self._emit(emit, "task.started", base)
                if parse_failed:
                    verdict, evidence = Verdict.UNDETERMINED, []
                else:
                    related = self._related(requirement, changes)
                    breaking = [c for c in related if c.severity == "BREAKING"]
                    if breaking:
                        verdict = Verdict.DEVIATES
                        cited = breaking
                    elif related:
                        verdict = Verdict.SATISFIED
                        cited = [c for c in related if c.severity == "NON_BREAKING"]
                    else:
                        verdict, cited = Verdict.NOT_FOUND, []
                    evidence = [self._evidence(case, change, changes.index(change))
                                for change in cited]
                finding = Finding(id=f"{case.id}:finding:{requirement.id}", case_id=case.id,
                                  requirement_id=requirement.id, verdict=verdict, evidence=evidence,
                                  confidence=Confidence.L0)
                findings.append(finding)
                self._emit(emit, "finding.created", finding.model_dump(mode="json"), finding)
                continue
            finding = Finding(id=f"{case.id}:finding:{requirement.id}", case_id=case.id,
                              requirement_id=requirement.id, verdict=verdict, evidence=evidence,
                              confidence=Confidence.L0)
            findings.append(finding)
            self._emit(emit, "finding.created", finding.model_dump(mode="json"), finding)
        return findings
