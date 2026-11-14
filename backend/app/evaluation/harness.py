"""Reproducible fixed-evidence ablations, separate from retrieval evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.review.engine import FakeReviewEngine, ReviewEngine
from app.review.schemas import Evidence, Finding, Requirement, ReviewCase
from app.review_adapters.spec_change_engine import SpecChangeEngine
from app.review_adapters.verdict_rules import assess
from .metrics import score


class LabelledRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    expected: Literal["SATISFIED", "PARTIAL", "DEVIATES", "NOT_FOUND"]
    expected_locators: list[str]
    evidence: list[Evidence]
    status: Literal["COMPLETE", "PARTIAL", "NO_EVIDENCE"]


class CorpusCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["requirement_review", "spec_change"] = "requirement_review"
    sources: dict[str, str]
    requirements: list[LabelledRequirement] = Field(min_length=1)
    provenance: str = "Hand-labelled synthetic example"

    @model_validator(mode="after")
    def validate_sources(self):
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate requirement IDs")
        if self.kind == "spec_change" and not {"old", "new"} <= self.sources.keys():
            raise ValueError("Spec cases need old and new source texts")
        for req in self.requirements:
            for evidence in req.evidence:
                if evidence.source_id not in self.sources:
                    raise ValueError("Evidence references missing source")
        return self


def load_corpus(path: str | Path) -> list[CorpusCase]:
    """Each UTF-8 JSON file holds a list of self-contained cases."""
    cases = [CorpusCase.model_validate(case) for file in sorted(Path(path).glob("*.json"))
             for case in json.loads(file.read_text(encoding="utf-8"))]
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("Corpus must be nonempty with unique case IDs")
    return cases


@dataclass(frozen=True)
class Condition:
    """Factory receives a case and a repeat-independent seed; use local RNGs only."""
    name: str
    factory: Callable[[CorpusCase, int], ReviewEngine]


class EvidenceEngine:
    """Legacy pipeline status mapping, optionally overridden by conflict rules."""

    def __init__(self, item: CorpusCase, mode: str):
        self.item, self.mode = item, mode

    def propose_requirements(self, case):
        return _requirements(self.item)

    def run(self, case, requirements, budget, emit):
        inputs = {r.id: r for r in self.item.requirements}
        findings = []
        for req in requirements:
            labelled = inputs[req.id]
            evidence = list(labelled.evidence)
            verdict = {"COMPLETE": "SATISFIED" if evidence else "UNDETERMINED", "PARTIAL": "PARTIAL",
                       "NO_EVIDENCE": "NOT_FOUND"}[labelled.status]
            if self.mode == "rules" and evidence and labelled.status != "NO_EVIDENCE":
                assessment = assess(req.text, evidence)
                if assessment.conflicting:
                    verdict = "DEVIATES"
                    evidence = list(assessment.conflicting)
                    evidence.extend(e for e in assessment.supporting if e not in evidence)
            elif self.mode == "naive":
                tokens = set(re.findall(r"\w+", req.text.casefold()))
                if any(tokens & set(re.findall(r"\w+", e.excerpt.casefold())) for e in evidence):
                    verdict = "DEVIATES"
            finding = Finding(id=f"{case.id}:{req.id}", case_id=case.id,
                              requirement_id=req.id, verdict=verdict, evidence=evidence, confidence="L0")
            emit(finding)
            findings.append(finding)
        return findings


def _spec_factory(item, seed):
    if item.kind == "spec_change":
        return SpecChangeEngine(lambda _: item.sources["old"], lambda _: item.sources["new"])
    return EvidenceEngine(item, "rules")


def default_conditions() -> list[Condition]:
    return [
        Condition("A_baseline_fake", lambda item, seed: FakeReviewEngine(
            evidence=[e for r in item.requirements for e in r.evidence], delay_ms=0)),
        Condition("C_verdict_rules", lambda item, seed: EvidenceEngine(item, "rules")),
        Condition("C_minus_rules", lambda item, seed: EvidenceEngine(item, "legacy")),
        Condition("naive_overlap", lambda item, seed: EvidenceEngine(item, "naive")),
        Condition("D_spec_change", _spec_factory),
    ]


def _requirements(item):
    return [Requirement(id=r.id, case_id=item.id, text=r.text, origin="USER", confirmed=True, order=i)
            for i, r in enumerate(item.requirements)]


@dataclass
class EvaluationResult:
    results: dict
    latencies: list[dict] = field(default_factory=list, compare=False, repr=False)


def run(conditions: list[Condition], corpus: list[CorpusCase], repeats: int = 3,
        seed: int = 0) -> EvaluationResult:
    """No wall clock enters results or equality; latency covers factory + engine."""
    if repeats < 1 or not conditions or not corpus:
        raise ValueError("Require positive repeats, conditions and corpus")
    if len({c.name for c in conditions}) != len(conditions):
        raise ValueError("Duplicate condition names")
    if len({c.id for c in corpus}) != len(corpus):
        raise ValueError("Duplicate case IDs")
    payload = {"seed": seed, "repeats": repeats, "conditions": [],
               "limitations": "Synthetic fixed evidence and supplied statuses; no retrieval, provider, "
               "translation or production accuracy claims. Repeats are not independent samples. "
               "D_spec_change uses the OpenAPI adapter on spec items; other conditions use corpus evidence."}
    latencies = []
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for condition in conditions:
        runs = []
        for repeat in range(repeats):
            rows = []
            for index, item in enumerate(corpus):
                case = ReviewCase(id=item.id, owner_user_id="evaluation", title=item.id,
                                  kind=item.kind, source_ids=list(item.sources), old_source_id="old",
                                  new_source_id="new", request_text="Evaluation", created_at=epoch, updated_at=epoch)
                started = perf_counter()
                engine = condition.factory(item.model_copy(deep=True), seed + index)
                findings = engine.run(case, _requirements(item), None, lambda *_: None)
                latencies.append({"condition": condition.name, "repeat": repeat, "case_id": item.id,
                                  "seconds": perf_counter() - started})
                by_id = {f.requirement_id: f for f in findings}
                if len(by_id) != len(findings) or set(by_id) != {r.id for r in item.requirements}:
                    raise ValueError("Engine must return exactly one finding per requirement")
                for req in item.requirements:
                    finding = by_id[req.id]
                    rows.append({"case_id": item.id, "requirement_id": req.id, "expected": req.expected,
                                 "predicted": finding.verdict.value, "expected_locators": req.expected_locators,
                                 "cited_locators": [e.locator for e in finding.evidence]})
            runs.append({"repeat": repeat, "rows": rows, "metrics": score(rows)})
        payload["conditions"].append({"name": condition.name, "runs": runs,
                                      "consistent": all(r["rows"] == runs[0]["rows"] for r in runs)})
    return EvaluationResult(payload, latencies)
