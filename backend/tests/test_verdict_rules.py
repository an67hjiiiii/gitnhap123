"""Business examples for the pure, bilingual evidence comparison rules."""

from decimal import Decimal

import pytest

from app.review_adapters.verdict_rules import (
    CONFLICTS, SATISFIES, UNRELATED, assess, compare, extract_claims,
)


def quantitative(text):
    return next(c for c in extract_claims(text) if c.kind == "quantitative")


@pytest.mark.parametrize("requirement,evidence,expected", [
    ("retain logs for 180 days", "Audit logs are retained for 90 days", CONFLICTS),
    ("at least 12 characters", "at least 8 characters", CONFLICTS),
    ("at least 12 characters", "at least 12 characters", SATISFIES),
    ("at least 12 characters", "at least 16 characters", SATISFIES),
    ("expire after 30 minutes", "expire after 30 minutes of inactivity", SATISFIES),
    ("Mật khẩu tối thiểu 12 ký tự", "Mật khẩu có ít nhất 8 ký tự", CONFLICTS),
    ("MẬT KHẨU TỐI THIỂU 12 KÝ TỰ", "mat khau co it nhat 12 ky tu", SATISFIES),
    ("retain logs for 180 days", "retain backups for 90 days", UNRELATED),
    ("password at least 12 characters", "password expires after 30 days", UNRELATED),
    ("password at least 12 characters", "username at least 8 characters", UNRELATED),
    ("logs retained for 1 hour", "logs retained for 60 minutes", SATISFIES),
    ("logs retained for 1 year", "logs retained for 365 days", SATISFIES),
    ("logs retained for 1 year", "logs retained for 364 days", CONFLICTS),
    ("logs retained for 1 month", "logs retained for 30 days", SATISFIES),
    ("Tệp tối đa 1 GB", "Tệp không quá 1000 MB", SATISFIES),
    ("Phiên trong vòng 1 giờ", "Phiên trong vòng 60 phút", SATISFIES),
    ("Nhật ký đúng 1 năm", "Nhật ký đúng 365 ngày", SATISFIES),
    ("retry maximum 3 attempts", "retry maximum 4 times", CONFLICTS),
    ("retry tối đa 3 lần", "retry 2 attempts", SATISFIES),
    ("availability minimum 99.9 percent", "availability 99.95%", SATISFIES),
    ("timeout within 30 minutes", "timeout at most 20 minutes", SATISFIES),
    ("timeout at most 30 minutes", "timeout at most 60 minutes", CONFLICTS),
    ("password at least 12 characters", "password 8 characters", CONFLICTS),
    ("password at least 12 characters", "password at most 8 characters", CONFLICTS),
    ("password at least 12 characters", "password at most 16 characters", UNRELATED),
    ("timeout exactly 30 minutes", "timeout at least 60 minutes", CONFLICTS),
    ("timeout exactly 30 minutes", "timeout at most 20 minutes", CONFLICTS),
    ("timeout exactly 30 minutes", "timeout at most 60 minutes", UNRELATED),
    ("timeout at most 30 minutes", "timeout at least 60 minutes", CONFLICTS),
])
def test_quantitative_business_cases(requirement, evidence, expected):
    assert compare(quantitative(requirement), quantitative(evidence)) == expected


@pytest.mark.parametrize("phrase,op", [
    ("at least", ">="), ("minimum", ">="), ("ít nhất", ">="), ("tối thiểu", ">="),
    ("at most", "<="), ("maximum", "<="), ("không quá", "<="), ("tối đa", "<="),
    ("exactly", "=="), ("đúng", "=="), ("within", "<="), ("trong vòng", "<="),
    ("", "=="),
])
def test_extract_comparators_and_original_span(phrase, op):
    text = f"Mật khẩu {phrase} 12 ký tự"
    claim = quantitative(text)
    assert claim.op == op
    assert claim.value == Decimal(12)
    assert claim.unit == "characters"
    assert claim.span == text
    assert set(claim.subject_hint.split()) == {"mat", "khau"}


@pytest.mark.parametrize("requirement,evidence,expected", [
    ("Services must not store plaintext passwords", "Services must store plaintext passwords", CONFLICTS),
    ("Services must store plaintext passwords", "Services must not store plaintext passwords", CONFLICTS),
    ("Services never store plaintext passwords", "Services always store plaintext passwords", CONFLICTS),
    ("Hệ thống không được lưu mật khẩu", "Hệ thống phải lưu mật khẩu", CONFLICTS),
    ("Hệ thống phải lưu mật khẩu", "Hệ thống không được lưu mật khẩu", CONFLICTS),
    ("Services must not store plaintext passwords", "Services never store plaintext passwords", SATISFIES),
    ("Users must encrypt", "Users must not decrypt", UNRELATED),
    ("Services must not store passwords", "Clients must store tokens", UNRELATED),
])
def test_explicit_polarity(requirement, evidence, expected):
    assert compare(extract_claims(requirement)[0], extract_claims(evidence)[0]) == expected


def test_mixed_assessment_preserves_items_and_explains_conflict():
    good = {"excerpt": "Audit logs retained for 180 days", "id": "good"}
    bad = {"excerpt": "Audit logs retained for 90 days", "id": "bad"}
    unrelated = {"excerpt": "Backups retained for 30 days"}
    result = assess("retain logs for 180 days", [good, bad, unrelated])
    assert result.verdict_hint == "DEVIATES"
    assert result.supporting == [good]
    assert result.conflicting == [bad]
    assert result.conflicting[0] is bad
    assert "180 days" in result.notes[0] and "90 days" in result.notes[0]
    assert "Conflicting claim" in result.notes[0]
    assert result == assess("retain logs for 180 days", [good, bad, unrelated])


@pytest.mark.parametrize("text", ["", "No quantitative claims", "twelve characters", "-12 characters"])
def test_unknown_claims_do_not_create_conflicts(text):
    assert extract_claims(text) == []
    result = assess("at least 12 characters", [text])
    assert result.verdict_hint == UNRELATED
    assert result.conflicting == []


def test_clauses_keep_unrelated_quantities_separate():
    result = assess("retain logs for 180 days", [
        "Audit logs retained for 180 days; backups retained for 30 days.",
    ])
    assert result.verdict_hint == SATISFIES
    assert result.conflicting == []


def test_one_excerpt_can_support_and_conflict_without_losing_provenance():
    text = "Logs retained for 180 days. Logs retained for 90 days."
    result = assess("retain logs for 180 days", [text])
    assert result.conflicting == result.supporting == [text]
    assert result.verdict_hint == "DEVIATES"


def test_negated_quantities_are_left_unknown():
    assert not any(c.kind == "quantitative" for c in extract_claims("logs not retained for 30 days"))


@pytest.mark.parametrize("items", [[], [""], ["logs retained for 90 days"],
                                        ["logs retained for 180 days"],
                                        ["backups retained for 90 days"]])
def test_deviates_requires_conflicting_evidence(items):
    result = assess("retain logs for 180 days", items)
    assert (result.verdict_hint == "DEVIATES") == bool(result.conflicting)
