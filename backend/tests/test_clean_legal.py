import hashlib

import pytest

from app.ingestion.clean import clean_legal_text, document_vocabulary
from app.ingestion.documents import extract_document
from app.retrieval.text import normalize_text


@pytest.mark.parametrize(("raw", "expected"), [
    ("đào t ạo", "đào tạo"),
    ("ba n hành", "ban hành"),
    ("kiế n áp", "kiến áp"),
    ("có hi ệu lực và thay th ế", "có hiệu lực và thay thế"),
    ("phạm vi áp dụng theo đơn vị m 2", "phạm vi áp dụng theo đơn vị m 2"),
])
def test_unambiguous_consonant_fragments(raw, expected):
    assert clean_legal_text(raw)[0] == expected


@pytest.mark.parametrize(("raw", "expected", "intact"), [
    ("Xây dự ng hệ thống", "Xây dựng hệ thống", "Xây dựng hệ thống"),
    ("đào tạo t ổ chức", "đào tạo tổ chức", "đào tạo tổ chức"),
    ("cá n hân", "cá nhân", "cá nhân"),
    ("theo m ột", "theo một", "theo một"),
    ("công tác h ọc", "công tác học", "công tác học"),
    ("và m ức", "và mức", "và mức"),
    ("ban h ành", "ban hành", "ban hành"),
    ("đổi m ới", "đổi mới", "đổi mới"),
])
def test_document_vocabulary_repairs_reviewed_cases(raw, expected, intact):
    text, stats = clean_legal_text(intact + ".\n" + raw)
    assert text.splitlines()[-1] == expected
    assert stats["syllable_joins"] == 1
    assert stats["ambiguous"] == 0


def test_ambiguous_without_evidence_or_with_tied_frequencies():
    for raw in ("cá n hân", "Xây dự ng hệ thống", "cán hân.\ncá nhân.\ncá n hân"):
        text, stats = clean_legal_text(raw)
        assert text == raw
        assert stats["ambiguous"] == 1
        assert stats["syllable_joins"] == 0


def test_vocabulary_is_local_and_not_trained_on_broken_fragments():
    assert clean_legal_text("cá nhân.\ncá n hân")[0].endswith("cá nhân")
    text, stats = clean_legal_text("cá n hân.\ncá n hân")
    assert text == "cá n hân.\ncá n hân"
    assert stats["ambiguous"] == 2
    syllables, pairs = document_vocabulary("hi ệu lực.\ncó hiệu lực")
    assert syllables["hi"] == syllables["ệu"] == 0
    assert syllables["hiệu"] == pairs["hiệu", "lực"] == 1


def test_measured_syllable_rules_and_normal_words():
    text, stats = clean_legal_text("có hi ệu lực và thay th ế\nđào t ạo theo quy định")
    assert text == "có hiệu lực và thay thế đào tạo theo quy định"
    assert stats["syllable_joins"] == 3
    assert clean_legal_text("ban hành quy chế tuyển sinh và đào tạo")[1]["syllable_joins"] == 0


def test_noise_requires_three_occurrences_and_joins_pages():
    raw = "câu chưa\n1\nKý bởi: A\n\f\nxong.\n2\nKý bởi: B\nCÔNG BÁO số 1\n3\nKý bởi: C\nCÔNG BÁO số 2\nCÔNG BÁO số 3"
    text, stats = clean_legal_text(raw)
    assert text == "câu chưa xong."
    assert stats["noise_lines_removed"] == 9
    text, stats = clean_legal_text("1\nKý bởi: A\nCÔNG BÁO số 1\n2")
    assert stats["noise_lines_removed"] == 0
    assert "Ký bởi:" in text


def test_sentence_and_clause_boundaries_remain():
    text, _ = clean_legal_text("Kết thúc.\ntrang sau\nĐiều 2. Nội dung\n1. mục thứ nhất\n2. mục tiếp theo")
    assert "Kết thúc.\ntrang sau\nĐiều 2." in text
    assert "\n1." in text and "\n2." in text


def test_observed_false_joins_and_previous_syllable():
    text, stats = clean_legal_text("phạm vi áp dụng theo đơn vị m 2, dự kiế n áp dụng, ba n hành")
    assert text == "phạm vi áp dụng theo đơn vị m 2, dự kiến áp dụng, ban hành"
    assert stats["syllable_joins"] == 2


def test_cleaning_off_preserves_entire_extraction(monkeypatch):
    raw = "\ufeff có hi ệu lực\r\n\r\n1\r\n2\r\n3 "
    monkeypatch.delenv("INGEST_CLEAN", raising=False)
    before = extract_document(raw, "example.txt")
    monkeypatch.setenv("INGEST_CLEAN", "off")
    assert extract_document(raw, "example.txt") == before
    assert before.text == normalize_text(raw)
    assert before.provenance["source_hash"] == hashlib.sha256(normalize_text(raw).encode()).hexdigest()
    assert "cleaner_version" not in before.provenance
    monkeypatch.setenv("INGEST_CLEAN", "rules")
    after = extract_document(raw, "example.txt")
    assert after.text == "có hiệu lực"
    assert after.provenance["cleaning_stats"]["syllable_joins"] == 1
    assert after.provenance["cleaner_version"]
