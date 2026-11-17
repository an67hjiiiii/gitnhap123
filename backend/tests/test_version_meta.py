from app.ingestion.clean import clean_legal_text
from app.ingestion.version_meta import propose_version
import pytest


def test_synthetic_draft_and_evidence():
    proposal = propose_version("Số hiệu: CS-DN-01\nPhiên bản: 3.0\nNgày dự thảo: 20/10/2026\nHiệu lực dự kiến: 01/03/2027\nTình trạng: DỰ THẢO", "draft.txt")
    assert proposal["doc_number"] == proposal["family_key"] == "CS-DN-01"
    assert proposal["version_label"] == "3.0"
    assert proposal["issued_on"] == "2026-10-20"
    assert proposal["effective_from"] == "2027-03-01"
    assert proposal["status"] == "draft"
    for field in ("doc_number", "family_key", "version_label", "issued_on", "effective_from", "status"):
        assert proposal["evidence"][field]


def test_replacement_with_version():
    p = propose_version("Số hiệu: CS-DN-01\nThay thế: Chính sách phiên bản 1.0 (CS-DN-01, hiệu lực từ 01/04/2025)", "policy.txt")
    assert p["relations"][0]["target_doc_number"] == "CS-DN-01"
    assert p["relations"][0]["target_version_label"] == "1.0"


@pytest.mark.parametrize("clean", [False, True])
def test_real_effective_scope_transition_and_filename(clean):
    raw = """Số:
Hà Nội, ngày 30 tháng 6 năm 2026
Căn cứ Thông tư số 99/2020/TT-BGDĐT;
Điều 15. Hiệu lực thi hành và quy định chuyển tiếp
1. Thông tư này có hi ệu lực từ ngày 30 tháng 6 năm 2026, áp dụng đối với các khóa thông báo tuyển sinh từ ngày 01 tháng 01 năm 2027 và thay th ế các Thông tư số 23/2021/TT -BGDĐT ngày 30 tháng 8 năm 2021 và Thông tư số 18/2021/TT-BGDĐT ngày 28 tháng 6 năm 2021.
2. Người học đã được tuyển chọn tiếp tục thực hiện quy định cũ.
3. Chánh Văn phòng chịu trách nhiệm.
Điều 16. Trách nhiệm
Thông tư số 77/2020/TT-BGDĐT.
"""
    p = propose_version(clean_legal_text(raw)[0] if clean else raw, "53_2026_TT-BGDDT.txt")
    assert p["doc_number"] == "53/2026/TT-BGDĐT"
    assert "từ tên tệp" in p["evidence"]["doc_number"]
    assert p["effective_from"] == "2026-06-30"
    assert p["applies_from"] == "2027-01-01"
    assert "Người học" in p["transition_note"]
    assert {r["target_doc_number"] for r in p["relations"]} == {"23/2021/TT-BGDĐT", "18/2021/TT-BGDĐT"}


def test_amends_is_not_replaces():
    p = propose_version("Số: 06/2025/TT-BGDĐT\nHà Nội, ngày 19 tháng 3 năm 2025\nTHÔNG TƯ\nSửa đổi, bổ sung Quy chế ban hành kèm theo Thông tư số 08/2022/TT-BGDĐT\nCăn cứ Thông tư số 88/2020/TT-BGDĐT;", "test.txt")
    assert [(r["type"], r["target_doc_number"]) for r in p["relations"]] == [("amends", "08/2022/TT-BGDĐT")]


def test_missing_invalid_dates_and_unknown_status():
    p = propose_version("Ngày ban hành: 31/02/2026\nKhông có số hiệu", "unknown.txt")
    assert p["issued_on"] is None
    assert p["status"] == "unverified"
    assert p["relations"] == []


def test_issue_date_from_own_annex_only():
    p = propose_version("(Kèm theo Thông tư số 50/2026/TT-BGDĐT ngày 30 tháng 6 năm 2026)", "50_2026_TT-BGDDT.txt")
    assert p["issued_on"] == "2026-06-30"
    p = propose_version("(Kèm theo Thông tư số 51/2026/TT-BGDĐT ngày 30 tháng 6 năm 2026)", "50_2026_TT-BGDDT.txt")
    assert p["issued_on"] is None


def test_implementation_article_cessation_and_blank_dates():
    p = propose_version("""Số:
Hà Nội, ngày     tháng     năm 2026
Điều 12. Điều khoản thi hành
1. Thông tư này có hiệu lực thi hành kể từ ngày     tháng     năm 2026, thay thế Thông tư số 02/2020/TT-BGDĐT ngày 05 tháng 02 năm 2020.
2. Thông tư số 03/2020/TT-BGDĐT ngày 01 tháng 3 năm 2020 hết hiệu lực thi hành từ ngày Thông tư này có hiệu lực.
""", "91_2026_TT_BGDDT.pdf")
    assert p["doc_number"] == "91/2026/TT-BGDĐT"
    assert p["issued_on"] is None and p["effective_from"] is None
    assert {(r["type"], r["target_doc_number"]) for r in p["relations"]} == {
        ("replaces", "02/2020/TT-BGDĐT"), ("replaces", "03/2020/TT-BGDĐT")}


def test_partial_repeal_amendment_and_cohort_in_effective_article():
    p = propose_version("""Điều 8. Hiệu lực và trách nhiệm thi hành
1. Thông tư này có hiệu lực thi hành từ ngày 10 tháng 5 năm 2026.
2. Điều 3; khoản 1 Điều 4 có hiệu lực thi hành cho khoá tuyển sinh từ năm 2027.
3. Bãi bỏ khoản 2 Điều 16 Thông tư số 11/2020/TT-BLĐTBXH và khoản 2 Điều 20 Thông tư số 12/2020/TT-BLĐTBXH.
4. Sửa đổi, bổ sung khoản 2 Điều 1 Quy chế ban hành kèm theo Thông tư số 13/2020/TT-BGDĐT như sau: “Quy định mới”.
""", "test.txt")
    assert p["effective_from"] == "2026-05-10"
    assert p["applies_from"] is None
    assert "2027" in p["applies_note"]
    assert {(r["type"], r["target_doc_number"]) for r in p["relations"]} == {
        ("partially_repeals", "11/2020/TT-BLĐTBXH"),
        ("partially_repeals", "12/2020/TT-BLĐTBXH"),
        ("amends", "13/2020/TT-BGDĐT")}


def test_inline_header_issue_date_is_explicit_evidence():
    p = propose_version("Số: 91/2026/TT-BGDĐT Hà Nội, ngày 27 tháng 3 năm 2026", "test.pdf")
    assert p["issued_on"] == "2026-03-27"
    assert "Hà Nội" in p["evidence"]["issued_on"]


def test_spaced_labels_without_cleaner_preserve_original_evidence():
    raw = """S ố: 08/2022/TT -BGDĐT
H à N ội, ng ày 06 th áng 6 n ăm 2022
Đi ều 9. Hi ệu l ực thi h ành và quy định chuy ển ti ếp
1. Th ông t ư n ày có hi ệu l ực thi h ành t ừ ng ày 22 th áng 7 n ăm 2022, á p d ụng đ ối v ới khóa tuyển sinh từ ngày 01 tháng 01 năm 2023 và thay th ế Thông tư số 09/2020/TT -BGDĐT.
2. Người học được tiếp tục học theo quy định cũ.
3. B ãi b ỏ khoản 2 Điều 3 Thông tư số 11/2020/TT -BLĐTBXH.
4. S ửa đ ổi, b ổ s ung khoản 1 Điều 2 Thông tư số 12/2020/TT -BGDĐT như sau: “Quy định mới”.
"""
    p = propose_version(raw, "unhelpful.pdf")
    assert p["doc_number"] == "08/2022/TT-BGDĐT"
    assert p["issued_on"] == "2022-06-06"
    assert p["effective_from"] == "2022-07-22"
    assert p["applies_from"] == "2023-01-01"
    assert p["transition_note"]
    assert "hi ệu l ực" in p["evidence"]["effective_from"]
    assert "TT -BGDĐT" in p["evidence"]["doc_number"]
    assert {r["type"] for r in p["relations"]} == {"replaces", "amends", "partially_repeals"}


def test_multiline_raw_labels_and_amendment_target():
    raw = """Điều 2. Thông tư này có hiệu lực từ ngày 30 tháng 6 năm 2026, áp dụng đối
với khóa tuyển sinh từ ngày 01 tháng 01 năm 2027.
2. Thông tư số 15/2018/TT-BGDĐT hết hiệu lực thi hành từ ngày Thông
tư này có hiệu lực.
3. Sửa đổi, bổ sung khoản 2 Điều 1 Quy chế ban hành kèm theo Thông
tư số 27/2011/TT-BGDĐT như sau: “Quy định mới”.
"""
    p = propose_version(raw, "test.pdf")
    assert p["applies_from"] == "2027-01-01"
    assert "đối\nvới" in p["applies_note"]
    assert {(r["type"], r["target_doc_number"]) for r in p["relations"]} == {
        ("replaces", "15/2018/TT-BGDĐT"), ("amends", "27/2011/TT-BGDĐT")}


@pytest.mark.parametrize("quoted_scope", [
    "Quy chế này áp dụng đối với học sinh ở trong khu nội trú",
    "Thông tư này áp dụng đối với học sinh ở trong khu nội trú từ ngày 01 tháng 01 năm 2027",
])
def test_tt40_scope_in_amendment_is_not_own_scope(quoted_scope):
    raw = f"""Điều 20. Hiệu lực thi hành
1. Thông tư này có hiệu lực thi hành từ ngày 01 tháng 01 năm 2026.
3. Sửa đổi, bổ sung Điều 1 Thông tư số 27/2011/TT-BGDĐT như sau:
“{quoted_scope}”.
"""
    p = propose_version(raw, "40_2026_TT_BGDDT.pdf")
    assert p["applies_note"] is None
    assert p["applies_from"] is None
    assert p["relations"][0]["target_doc_number"] == "27/2011/TT-BGDĐT"
