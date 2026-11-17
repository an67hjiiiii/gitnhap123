"""S6 acceptance: public construction table, normalized traps and pure intent."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

import pytest

from app.ingestion.documents import extract_document
from app.ingestion.version_diff import atoms, compare_units, diff_intent, diff_versions, topic_units

DATA = Path(os.getenv("S6_TEST_DATA", "D:/CAP1-Orchestration/work/version_test"))
POLICIES = {"Đăng nhập": "CS_DANGNHAP", "Nhật ký": "CS_NHATKY", "API": "CS_API"}


def texts(policy):
    return [extract_document((DATA / f"{policy}_v{v}.txt").read_bytes(), f"{policy}_v{v}.txt").text for v in (1, 2)]


@pytest.fixture
def corpus(monkeypatch):
    if not DATA.exists():
        pytest.skip("S6 public synthetic corpus is not installed")
    monkeypatch.setenv("INGEST_CLEAN", "rules")
    return {p: texts(p) for p in POLICIES.values()}


def test_public_answer_table_recall_and_false_positives(corpus):
    table = (DATA / "BANG_THAY_DOI_CHUAN.md").read_text(encoding="utf-8")
    diffs = {p: diff_versions(*values, p, include_text=True) for p, values in corpus.items()}
    hits, traps = [], []
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 6 or not re.fullmatch(r"[LGA]\d+", cells[0]):
            continue
        ident, policy, location, kind, _, _ = cells
        rows = diffs[POLICIES[policy]]
        number = re.search(r"Điều (\d+)(?:\.(\d+))?", location)
        clause = number[2]
        if "khoản 2" in location:
            clause = "2"
        label = "Điều " + number[1]
        if kind in {"DOI", "BO"}:
            found = [r for r in rows if r["kind"] == kind and r["old_article"] == label
                     and (clause is None or r["old_clause"] == clause)]
        elif kind == "THEM":
            found = [r for r in rows if r["kind"] == kind and r["new_article"] == label
                     and (clause is None or r["new_clause"] == clause)]
        elif kind == "GIA":
            found = [r for r in rows if r["old_article"] == label
                     and (clause is None or r["old_clause"] == clause)]
        else:  # CHUYEN: the matched article may move but must not be reported.
            found = [r for r in rows if r["old_article"] == label]
        if kind in {"DOI", "THEM", "BO"}:
            assert len(found) == 1, ident
            hits.append(ident)
        else:
            assert not found, ident
            traps.append(ident)
    assert len(hits) == 12 and len(traps) == 3
    assert sum(map(len, diffs.values())) == 12
    print("S6 synthetic: recall=12/12 false_positives=0/3")


@pytest.mark.parametrize("query,intent", [
    ("So sánh hai bản", "ALL"), ("Có thay đổi không?", "ALL"), ("Khác nhau thế nào?", "ALL"),
    ("Điểm mới trong chính sách", "THEM"), ("Thêm điều nào?", "THEM"),
    ("Mục bị bỏ?", "BO"), ("Bỏ điều gì?", "BO"), ("Có gì mới?", "NEW"),
    ("Thêm và bỏ những gì?", "ALL"), ("Mật khẩu dài bao nhiêu?", None),
])
def test_pure_diff_intent(query, intent):
    assert diff_intent(query) == intent
    assert diff_intent(unicodedata.normalize("NFD", query.upper())) == intent


@pytest.mark.parametrize("old,new", [("30 phút", "0,5 giờ"), ("12 tháng", "một năm"),
    ("01/03/2026", "1/3/2026"), ("100 yêu cầu mỗi phút", "100 yêu cầu/phút")])
def test_normalization(old, new):
    assert atoms(old) == atoms(new)


def test_atomic_units_and_modal():
    assert atoms("phải chờ 0,5 giờ đến 01/03/2026, 5%, 12 ký tự, 2 lần") == sorted(
        ["phải", "30 phút", "2026-03-01", "5 %", "12 ký tự", "2 lần"])
    assert atoms("không được") == ["không được"]
    assert atoms("có thể, bắt buộc, khuyến khích") == sorted(["có thể", "bắt buộc", "khuyến khích"])


def test_topic_equivalence_and_clause_addition(corpus):
    for policy, query, article, clause in [
        ("CS_DANGNHAP", "Thời gian mở khóa có thay đổi không?", "Điều 3", "2"),
        ("CS_API", "Thời hạn API key có thay đổi không?", "Điều 4", "1"),
        ("CS_NHATKY", "Sao lưu có thay đổi không?", "Điều 6", "1"),
    ]:
        old, new = corpus[policy]
        selected = topic_units(query, compare_units(old, new), family_label=new.splitlines()[0])
        assert len(selected) == 1
        assert selected[0]["old_article"] == article and selected[0]["old_clause"] == clause
        assert selected[0]["kind"] is None
    api = diff_versions(*corpus["CS_API"], include_text=True)
    added = [r for r in api if r["kind"] == "THEM"]
    assert len(added) == 1 and added[0]["new_clause"] == "2"
    assert "Retry-After" in added[0]["text_after"]


def test_dump_cli_exact_schema(corpus):
    result = subprocess.run([sys.executable, "-X", "utf8", "scripts/s6_dump_diff.py",
        str(DATA / "CS_API_v1.txt"), str(DATA / "CS_API_v2.txt"), "CS_API"], capture_output=True, check=True)
    rows = json.loads(result.stdout)
    assert len(rows) == 3
    assert all(set(row) == {"pair", "old_article", "new_article", "kind", "atoms_before", "atoms_after"} for row in rows)
    assert all(row["pair"] == "CS_API" for row in rows)
