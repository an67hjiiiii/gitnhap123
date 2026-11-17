"""P3 regression cases and pure numeric/sentence parsing contracts."""
import json
import re
from pathlib import Path

import pytest

from app.chat.answer_guard import (
    _false_change, _numeric_parts, _sentence_spans, guard_answer, split_sentences,
)
from app.review_adapters.slot_check import _numbers


CASES_PATH = Path(r"D:\CAP1-Orchestration\work\p3\guard_cases.jsonl")
CASES = ([json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
          if line.strip()] if CASES_PATH.is_file() else [])


@pytest.mark.parametrize("text", [
    "Theo TT. 50/2026, Điều 15. khoản 1 có hiệu lực.",
    "Theo NĐ. 08/2022, Khoản 2. nội dung tiếp tục.",
    "Theo QĐ. 12/2026, tr. 15 có ví dụ, v.v. và ghi chú.",
])
def test_abbreviations_and_legal_references_do_not_split(text):
    assert split_sentences(text) == [text]


def test_sentence_spans_preserve_decimal_markdown_and_offsets():
    text = "Phiên giữ 0.5 giờ. Câu tiếp theo!\n| Bản 2.0 | 12 ký tự. Hợp lệ. |\n  - Mục 1. Còn tiếp."
    expected = ["Phiên giữ 0.5 giờ.", "Câu tiếp theo!",
                "| Bản 2.0 | 12 ký tự. Hợp lệ. |", "- Mục 1. Còn tiếp."]
    assert split_sentences(text) == expected
    assert [text[a:b].strip() for a, b in _sentence_spans(text)] == expected
    assert split_sentences("") == []
    assert split_sentences("1. Mục 1. Nội dung.") == ["1. Mục 1. Nội dung."]


@pytest.mark.parametrize("text,canonical", [
    ("ngày 15 tháng 8 năm 2026", "2026-08-15"),
    ("ngày 15/08/2026", "2026-08-15"),
    ("ngày 15-8-2026", "2026-08-15"),
])
def test_dates_are_calendar_values_and_never_durations(text, canonical):
    quantities, dates, bare = _numeric_parts(text)
    assert dates == [canonical] and bare == [] and _numbers(quantities) == []


@pytest.mark.parametrize("reference", [
    "TT. 50/2026", "08/2022/TT-BGDĐT", "Điều 15. khoản 1 điểm a",
    "bản 2.0", "phiên bản 1.0", "v2", "1. Nội dung",
])
def test_identifiers_are_not_measurements(reference):
    quantities, dates, bare = _numeric_parts(reference)
    assert not _numbers(quantities) and not dates and not bare


def test_every_bare_number_is_checked_alongside_quantities():
    quantities, dates, bare = _numeric_parts("**30 phút**, mã 9999, bản 2.0")
    assert [s.value for s in _numbers(quantities)] == ["30"]
    assert dates == [] and bare == ["9999"]


@pytest.mark.parametrize("answer,expected", [
    ("Đổi từ 30 phút sang 0,5 giờ.", True),
    ("Thay đổi từ **30 phút** thành **0.5 giờ**.", True),
    ("Tăng từ 1 năm lên 12 tháng.", True),
    ("Giảm từ 1800 giây xuống 30 phút.", True),
    ("Tăng từ 90 ngày lên 180 ngày.", False),
    ("Đổi từ 30 phút sang 30 ngày.", False),
    ("Phiên hết hạn sau 30 phút.", False),
])
def test_false_change_uses_normalized_quantity_keys(answer, expected):
    assert _false_change(answer) is expected


@pytest.mark.parametrize("mode", ["drop", "mark"])
def test_equal_value_change_is_always_dropped(monkeypatch, mode):
    monkeypatch.setenv("GUARD_MODE", mode)
    answer = "Đổi từ 30 phút sang 0.5 giờ."
    result = guard_answer(answer, status="COMPLETE", evidence_texts=["Thời hạn 30 phút."])
    assert result.removed_claims == [answer]
    assert "FLAG_FALSE_CHANGE" in result.notes


@pytest.mark.parametrize("mode", [None, "drop", "mark", "invalid"])
@pytest.mark.parametrize("answer,value", [
    ("Mật khẩu hết hạn sau 90 ngày.", "90"),
    ("Mã HTTP là 429.", "429"),
    ("Mật khẩu đổi ngày 15 tháng 8 năm 2026.", "2026-08-15"),
])
def test_unverified_values_are_marked_only_in_mark_mode(monkeypatch, mode, answer, value):
    if mode is None:
        monkeypatch.delenv("GUARD_MODE", raising=False)
    else:
        monkeypatch.setenv("GUARD_MODE", mode)
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[
        "Nhật ký truy cập giữ 90 ngày, mã 429, bắt đầu ngày 15/08/2026.",
    ])
    if mode == "mark":
        assert result.answer == answer and result.removed_claims == []
        assert result.notes == ["FLAG_UNVERIFIED:" + value]
    else:
        assert result.removed_claims == [answer]


@pytest.mark.parametrize("mode", ["drop", "mark"])
def test_contradicted_and_absent_values_are_dropped_in_both_modes(monkeypatch, mode):
    monkeypatch.setenv("GUARD_MODE", mode)
    for answer in ("Phiên hết hạn sau 10 phút.", "Phiên hết hạn sau 9999 phút."):
        result = guard_answer(answer, status="COMPLETE", evidence_texts=[
            "Phiên hết hạn sau 15 phút.", "Khóa tài khoản sau 10 phút.",
        ])
        assert result.removed_claims == [answer]
        assert not any(note.startswith("FLAG_UNVERIFIED:") for note in result.notes)


def test_borrowed_modifiers_do_not_transfer_a_number_to_another_subject():
    result = guard_answer("Phiên đăng nhập hết hạn sau 10 phút.", status="COMPLETE",
                          evidence_texts=["Tài khoản khóa sau 10 phút đăng nhập sai."])
    assert result.removed_claims


def test_calendar_dates_compare_as_dates_and_reject_wrong_or_invalid_dates():
    source = "Thông tư có hiệu lực từ ngày 15 tháng 8 năm 2026."
    answer = "Thông tư có hiệu lực từ ngày 15/08/2026."
    assert guard_answer(answer, status="COMPLETE", evidence_texts=[source]).answer == answer
    for wrong in ("Thông tư có hiệu lực từ ngày 15/09/2026.",
                  "Thông tư có hiệu lực từ ngày 31 tháng 2 năm 2026."):
        assert guard_answer(wrong, status="COMPLETE", evidence_texts=[source]).removed_claims == [wrong]


def test_removal_keeps_markdown_rows_indentation_and_bold():
    valid = "| Mật khẩu | **12 ký tự** |\n  - Đổi mật khẩu sau 90 ngày."
    answer = valid + "\n  - Mật khẩu hết hạn sau 9999 ngày."
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[
        "Mật khẩu có 12 ký tự. Đổi mật khẩu sau 90 ngày.",
    ])
    assert result.answer == valid
    assert result.removed_claims == ["- Mật khẩu hết hạn sau 9999 ngày."]


@pytest.mark.parametrize("mode", ["drop", "mark"])
@pytest.mark.parametrize("case", CASES or [None], ids=[c['id'] for c in CASES] or ["missing-corpus"])
def test_labeled_guard_corpus(monkeypatch, mode, case):
    if case is None:
        pytest.skip(f"Missing labeled corpus: {CASES_PATH}")
    monkeypatch.setenv("GUARD_MODE", mode)
    result = guard_answer(case['answer'], status="COMPLETE", evidence_texts=case['evidence'])
    removed = bool(result.removed_claims) or any(n.startswith("ANSWER_REPLACED") for n in result.notes)
    flagged = any(n.startswith("FLAG_") for n in result.notes)
    if case['expect'] == 'keep':
        norm = lambda s: re.sub(r"\s+", " ", s).strip()
        assert not removed and not flagged
        assert all(norm(line) in norm(result.answer) for line in case['answer'].splitlines() if line.strip())
        assert case['answer'].count('\n') <= result.answer.count('\n')
    elif case['expect'] == 'drop':
        assert removed
    else:
        assert removed or flagged


@pytest.mark.parametrize("answer,source,keep", [
    ("Theo quy chế vận hành bản 3.1, cảnh báo 731 phải được ghi nhận.",
     "Hệ thống phát mã 731. Cảnh báo phải được ghi nhận.", True),
    ("Căn cứ hướng dẫn CS-SYS-07, sự kiện 642 phải được ghi nhận.",
     "Hệ thống phát mã 642. Sự kiện phải được ghi nhận.", True),
    ("Theo quy chế bản 3.1, cảnh báo 732 phải được ghi nhận.",
     "Hệ thống phát mã 731. Cảnh báo phải được ghi nhận.", False),
    ("Cảnh báo 731 phải được ghi nhận.",
     "Kho lưu trữ có mã 731. Cảnh báo phải được ghi nhận.", False),
    ("Cảnh báo 731 phải được ghi nhận.",
     "Cảnh báo phải được ghi nhận. Kho lưu trữ có mã 731.", False),
    ("Cảnh báo 731 phải được ghi nhận.",
     "Hệ thống phát mã 731. Cảnh báo phải được ghi nhận.", True),
    ("Kể từ ngày 9/4/2027, QĐ. 12/2024 bị thay thế bởi Quyết định 18/2027.",
     "Quyết định này có hiệu lực từ ngày 9 tháng 4 năm 2027 và thay thế Quyết định 12/2024.", True),
    ("Từ ngày 3/11/2028, NĐ. 17/2023 bị thay thế bởi Nghị định 21/2028.",
     "Nghị định này có hiệu lực từ ngày 3 tháng 11 năm 2028 và thay thế Nghị định 17/2023.", True),
    ("Vào ngày 9/4/2027, giấy phép bị thu hồi.",
     "Giấy phép bị thu hồi vào ngày 9 tháng 4 năm 2027.", True),
    ("Kể từ ngày 10/4/2027, QĐ. 12/2024 bị thay thế bởi Quyết định 18/2027.",
     "Quyết định này có hiệu lực từ ngày 9 tháng 4 năm 2027 và thay thế Quyết định 12/2024.", False),
    ("Vào ngày 9/4/2027, giấy phép bị thu hồi.",
     "Giấy phép bị thu hồi vào ngày 10/4/2027. Chứng chỉ bị thu hồi vào ngày 9/4/2027.", False),
    ("Theo quy chế CS-SYS-07, phiên đăng nhập hết hạn sau 12 phút.",
     "Tài khoản bị khóa sau 12 phút đăng nhập sai.", False),
])
def test_clause_subject_and_adjacent_figure_regressions(monkeypatch, answer, source, keep):
    monkeypatch.setenv("GUARD_MODE", "drop")
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[source])
    assert bool(result.removed_claims) is not keep
    if keep:
        assert result.answer == answer and result.notes == []


def test_adjacent_subject_context_cannot_cross_cited_chunks(monkeypatch):
    monkeypatch.setenv("GUARD_MODE", "drop")
    answer = "Cảnh báo 731 phải được ghi nhận."
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[
        "Hệ thống phát mã 731.", "Cảnh báo phải được ghi nhận.",
    ])
    assert result.removed_claims == [answer]


@pytest.mark.parametrize("reference", ["CS-SYS-07", "QT-OPS-125", "HD-ABC-03/2028"])
def test_hyphenated_document_identifiers_are_not_bare_numbers(reference):
    quantity, dates, bare = _numeric_parts(reference)
    assert not _numbers(quantity) and not dates and not bare


@pytest.mark.parametrize("source,keep", [
    ("Thiết bị cấp khóa dự phòng. Khóa hết hạn sau 48 giờ.", True),
    ("Khóa vận hành hết hạn sau 48 giờ. Thiết bị cấp khóa dự phòng.", False),
])
def test_neighbor_context_accepts_shortened_but_not_different_subject(monkeypatch, source, keep):
    monkeypatch.setenv("GUARD_MODE", "drop")
    answer = "Khóa dự phòng hết hạn sau 2 ngày."
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[source])
    assert bool(result.removed_claims) is not keep
    if keep:
        assert result.answer == answer and result.notes == []


@pytest.mark.parametrize("mode", ["drop", "mark"])
def test_uncited_support_uses_same_subject_and_records_note(monkeypatch, mode):
    monkeypatch.setenv("GUARD_MODE", mode)
    answer = "Nhật ký vận hành được lưu trong 48 giờ."
    cited = ["Nhật ký vận hành được lưu trong 12 giờ."]
    result = guard_answer(answer, status="COMPLETE", cited_texts=cited,
                          evidence_texts=cited + ["Nhật ký vận hành được lưu trong 2 ngày."])
    assert result.answer == answer and not result.removed_claims
    assert result.notes == ["SUPPORTED_UNCITED:48"]
    assert cited == ["Nhật ký vận hành được lưu trong 12 giờ."]


@pytest.mark.parametrize("extra", [
    "Nhật ký sự cố được lưu trong 48 giờ.",
    "Nhật ký vận hành hết hạn sau 48 giờ.",
    "Nhật ký vận hành được lưu trong 48 phút.",
])
def test_uncited_support_rejects_other_entity_property_or_unit(extra):
    answer = "Nhật ký vận hành được lưu trong 48 giờ."
    result = guard_answer(answer, status="COMPLETE",
                          cited_texts=["Nhật ký vận hành được lưu trong 12 giờ."], evidence_texts=[extra])
    assert result.removed_claims == [answer]
    assert not any(note.startswith("SUPPORTED_UNCITED:") for note in result.notes)


def test_uncited_support_rejects_explicit_other_version_even_with_replacement_reference():
    answer = "Theo bản 4.0, nhật ký vận hành được lưu trong 48 giờ."
    result = guard_answer(answer, status="COMPLETE",
                          cited_texts=["Phiên bản: 4.0\nNhật ký vận hành được lưu trong 12 giờ."],
                          evidence_texts=["Phiên bản: 5.0\nThay thế: bản 4.0\n"
                                          "Nhật ký vận hành được lưu trong 48 giờ."])
    assert result.removed_claims == [answer]


@pytest.mark.parametrize("answer,source,keep", [
    ("Hiện nay, thời gian lưu trữ của nhật ký sự cố là 72 giờ.",
     "Nhật ký sự cố được lưu trong 3 ngày.", True),
    ("Theo tài liệu HD_ROTATE_v7.md, thời hạn khóa dự phòng là 48 giờ.",
     "Khóa dự phòng hết hạn sau 2 ngày.", True),
    ("Tuy nhiên, tài liệu HD_SESSION_v4.txt ghi rằng phiên truy cập hết hạn sau 40 phút.",
     "Tài khoản bị khóa sau 40 phút truy cập sai.", False),
    ("Thời gian tự động mở khóa tài khoản là 20 phút.",
     "Tài khoản bị khóa sau 20 phút. Tài khoản được mở khóa sau 50 phút.", False),
])
def test_reporting_scaffolding_preserves_numeric_property(answer, source, keep):
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[source])
    assert bool(result.removed_claims) is not keep
    if keep:
        assert result.answer == answer and result.notes == []


@pytest.mark.parametrize("reference", [
    "mục 9", "bản cũ (4.0)", "bản 3.2 và 4.1", "chunk ID c0712",
    "mã đoạn src_abcd_c0077", "HD_SESSION_DRAFT_v7.txt",
    "Hệ thống được nâng cấp từ 3.1 lên 4.2, với thay đổi mới.",
])
def test_more_reference_forms_are_not_measurements(reference):
    quantity, dates, bare = _numeric_parts(reference)
    assert not _numbers(quantity) and not dates and not bare


@pytest.mark.parametrize("preposition", ["theo", "tại", "ở"])
def test_sentence_boundary_after_terminal_legal_reference(preposition):
    first = f"Nội dung này được ghi {preposition} Điều 7."
    second = "Quy chế mới có hiệu lực."
    assert split_sentences(first + " " + second) == [first, second]
    heading = "Điều 7. Quy chế mới có hiệu lực."
    assert split_sentences(heading) == [heading]


@pytest.mark.parametrize("answer,keep", [
    ("Quy chế vận hành được ban hành ngày 12/05/2028.", True),
    ("Quy chế vận hành có hiệu lực từ ngày 02/06/2028.", True),
    ("Quy chế vận hành có hiệu lực từ ngày 12/05/2028.", False),
    ("Hướng dẫn cấp phép được ban hành ngày 12/05/2028.", False),
])
def test_metadata_title_inherits_only_its_own_fields(answer, keep):
    source = ("QUY CHẾ VẬN HÀNH\nSố hiệu: QC-OPS-17\nPhiên bản: 4.0\n"
              "Đơn vị: Trung tâm kỹ thuật\nNgày ban hành: 12/05/2028\nHiệu lực từ: 02/06/2028")
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[source])
    assert bool(result.removed_claims) is not keep
    if keep:
        assert result.answer == answer and result.notes == []


def _legal_source(filename, version, body):
    return (f"Tài liệu: {filename}\nPhiên bản: Số hiệu: CS-API-03; "
            f"Phiên bản: {version}; Hiệu lực từ: 01/10/2026\n{body}")


@pytest.mark.parametrize("reference", ["bản 1.0", "phiên bản 1.0", "v1", "CS_API_v1.txt"])
@pytest.mark.parametrize("mode", ["drop", "mark"])
def test_legal_labels_block_other_version_including_uncited(monkeypatch, reference, mode):
    monkeypatch.setenv("GUARD_MODE", mode)
    answer = f"Theo {reference}, mỗi API key được gửi tối đa 300 yêu cầu mỗi phút."
    cited = [_legal_source("CS_API_v1.txt", "1.0", "Mỗi API key được gửi tối đa 100 yêu cầu mỗi phút.")]
    other = _legal_source("CS_API_v2.txt", "2.0", "Mỗi API key được gửi tối đa 300 yêu cầu mỗi phút.")
    for citations in [cited, cited + [other]]:
        result = guard_answer(answer, status="COMPLETE", cited_texts=citations, evidence_texts=cited + [other])
        assert result.removed_claims == [answer]
        assert not any(n.startswith("SUPPORTED_UNCITED:") for n in result.notes)


def test_legal_filename_rejects_another_document_with_same_version():
    answer = "Theo CS_API_v2.txt, mỗi API key được gửi tối đa 300 yêu cầu mỗi phút."
    source = _legal_source("CS_OTHER_v2.txt", "2.0", "Mỗi API key được gửi tối đa 300 yêu cầu mỗi phút.")
    assert guard_answer(answer, status="COMPLETE", evidence_texts=[source]).removed_claims == [answer]


def test_legal_draft_cannot_borrow_published_number():
    answer = "Theo bản dự thảo, mỗi API key được gửi tối đa 300 yêu cầu mỗi phút."
    sources = [_legal_source("CS_API_DUTHAO_v3.txt", "3.0; Tình trạng: Dự thảo", "Mỗi API key được gửi tối đa 500 yêu cầu mỗi phút."),
               _legal_source("CS_API_v2.txt", "2.0", "Mỗi API key được gửi tối đa 300 yêu cầu mỗi phút.")]
    assert guard_answer(answer, status="COMPLETE", evidence_texts=sources).removed_claims == [answer]


def test_legal_metadata_date_supports_any_claim_on_matching_chunk():
    answer = "Theo CS_API_v2.txt, quy định này có hiệu lực từ 01/10/2026."
    source = _legal_source("CS_API_v2.txt", "2.0", "Mỗi API key được gửi tối đa 300 yêu cầu mỗi phút.")
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[source])
    assert result.answer == answer and result.notes == []


def test_legal_no_version_keeps_uncited_support():
    answer = "Mỗi API key được gửi tối đa 300 yêu cầu mỗi phút."
    old = _legal_source("CS_API_v1.txt", "1.0", "Mỗi API key được gửi tối đa 100 yêu cầu mỗi phút.")
    new = _legal_source("CS_API_v2.txt", "2.0", "Mỗi API key được gửi tối đa 300 yêu cầu mỗi phút.")
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[old, new], cited_texts=[old])
    assert result.answer == answer and result.notes == ["SUPPORTED_UNCITED:300"]


@pytest.mark.parametrize("verb", ["điều chỉnh", "chuyển", "nâng"])
def test_additional_false_change_verbs(verb):
    answer = f"Thời hạn đã được {verb} từ 30 phút lên 0,5 giờ."
    result = guard_answer(answer, status="COMPLETE", evidence_texts=["Thời hạn là 30 phút."])
    assert result.removed_claims == [answer] and "FLAG_FALSE_CHANGE" in result.notes


def test_parenthesized_effective_version_is_metadata_and_still_filters_numbers():
    answer = "Thông tin này được xác nhận trong phiên bản đang có hiệu lực (2.0) từ ngày 01/10/2026."
    source = _legal_source("CS_API_v2.txt", "2.0", "API key hết hạn sau 12 tháng.")
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[source])
    assert result.answer == answer and result.notes == []
    wrong = "Phiên bản đang có hiệu lực (1.0) quy định API key hết hạn sau 12 tháng."
    assert guard_answer(wrong, status="COMPLETE", evidence_texts=[source]).removed_claims == [wrong]


@pytest.mark.parametrize("mode", ["drop", "mark"])
def test_other_version_cannot_supply_duration_or_effective_date(monkeypatch, mode):
    monkeypatch.setenv("GUARD_MODE", mode)
    source = _legal_source("CS_API_v2.txt", "2.0", "API key hết hạn sau 12 tháng.")
    for answer in ["Theo bản 1.0, API key hết hạn sau 12 tháng.",
                   "Theo bản 1.0, quy định có hiệu lực từ 01/10/2026."]:
        result = guard_answer(answer, status="COMPLETE", evidence_texts=[source], cited_texts=[source])
        assert result.removed_claims == [answer]
        assert not any(n.startswith("SUPPORTED_UNCITED:") for n in result.notes)


def test_same_labeled_version_can_supply_uncited_duration():
    answer = "Theo bản 2.0, API key hết hạn sau 12 tháng."
    source = _legal_source("CS_API_v2.txt", "2.0", "API key hết hạn sau 12 tháng.")
    cited = _legal_source("CS_API_v2.txt", "2.0", "API key hết hạn sau 6 tháng.")
    result = guard_answer(answer, status="COMPLETE", evidence_texts=[source, cited], cited_texts=[cited])
    assert result.answer == answer and result.notes == ["SUPPORTED_UNCITED:12"]
