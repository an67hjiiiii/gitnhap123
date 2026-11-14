"""Slot coverage on Vietnamese text, equivalent units and number words (characterization only).

Passing tests pin behaviour that is already correct. The strict xfail tests are real
wrong verdict demotions found by probing; each states the smallest proposed fix.
No production behaviour is changed by this file.
"""

import pytest

from app.review_adapters.slot_check import check_slots, extract_slots


def missing(requirement, *evidence):
    return list(check_slots(requirement, evidence).missing_slots)


@pytest.mark.parametrize("requirement,evidence", [
    ("Mật khẩu phải có ít nhất 12 ký tự.", "Mật khẩu tối thiểu 12 ký tự."),
    ("Phiên hết hạn trong vòng 30 phút.", "Phiên hết hạn sau 30 phút không hoạt động."),
    ("Phản hồi trong 0,5 giây.", "Phản hồi dưới 0,5 giây."),
    ("Khóa sau 5 lần đăng nhập sai.", "Tài khoản bị khóa sau 5 lần thử sai."),
    ("Hết hạn sau 5 phút.", "Expires after 5 minutes."),
    ("Tên tệp tối đa 1.000 ký tự.", "Tên tệp tối đa 1.000 ký tự."),
])
def test_vietnamese_numbers_and_unit_aliases_are_covered(requirement, evidence):
    assert missing(requirement, evidence) == []


@pytest.mark.parametrize("requirement,evidence", [
    ("Nhật ký xác thực được giữ 180 ngày.", "Nhật ký xác thực được lưu 6 tháng."),
    ("Vé sự cố được giữ 30 ngày.", "Vé sự cố được giữ 1 tháng."),
    ("Dữ liệu được giữ 1 năm.", "Dữ liệu được giữ 365 ngày."),
    ("Backups kept 7 days.", "Backups are kept for 1 week."),
    ("Tokens expire in 24 hours.", "Tokens expire after 1 day."),
    ("Phiên hết hạn trong vòng 30 phút.", "Phiên hết hạn sau 0,5 giờ."),
    ("Uploads up to 2 GB.", "Uploads up to 2000 MB."),
    ("Coverage at least 80%.", "Coverage at least 80 percent."),
])
def test_equivalent_units_are_covered(requirement, evidence):
    assert missing(requirement, evidence) == []


def test_different_quantity_or_vietnamese_missing_entity_still_demotes():
    assert missing("Vé được giữ 30 ngày.", "Vé được giữ 90 ngày.") == ["number:30 days"]
    assert missing("Hệ thống phải gửi email cho Quản trị viên.", "Hệ thống gửi SMS.") == ["entity:quản"]


def test_multiword_vietnamese_name_only_keeps_its_capitalised_first_word():
    # Known weak slot: "Quản trị viên" becomes the single entity "quản", so unrelated
    # text such as "quản lý" would also cover it (a missed demotion, not a wrong one).
    assert [str(s) for s in extract_slots("Hệ thống phải gửi email cho Quản trị viên.")] == ["entity:quản"]
    assert missing("Hệ thống phải gửi email cho Quản trị viên.", "Chỉ quản lý được xem.") == []


# --- wrong demotions found by probing (requirement value IS present in the evidence) ---

@pytest.mark.xfail(strict=True, reason=(
    "WRONG DEMOTION: '1.000 ký tự' (Vietnamese thousands dot) is read as 1, so evidence '1000 ký tự' "
    "is missing. Smallest fix: in slot_check._numbers treat a single dot followed by exactly 3 digits "
    "as a thousands separator when the unit is not a decimal-friendly one, or accept either reading."))
def test_vietnamese_thousands_dot_matches_plain_number():
    assert missing("Tên tệp tối đa 1.000 ký tự.", "Tên tệp tối đa 1000 ký tự.") == []


@pytest.mark.xfail(strict=True, reason=(
    "WRONG DEMOTION: fixed conversion gives 12 months = 360 days but 1 year = 365 days. "
    "Smallest fix: compare months and years through a calendar-month alias (12 months == 1 year) "
    "before falling back to seconds."))
def test_twelve_months_equal_one_year():
    assert missing("Dữ liệu được giữ 12 tháng.", "Dữ liệu được giữ 1 năm.") == []


@pytest.mark.xfail(strict=True, reason=(
    "WRONG DEMOTION: number words are not parsed, so 'thirty days' / 'ba mươi ngày' do not cover 30 days. "
    "Smallest fix: map a small closed list of English/Vietnamese number words (0-100) to digits "
    "in the evidence text before extracting quantities."))
@pytest.mark.parametrize("requirement,evidence", [
    ("Tickets retained for 30 days.", "Tickets are retained for thirty days."),
    ("Passwords need 12 characters.", "Passwords need twelve characters."),
    ("Vé được giữ 30 ngày.", "Vé được giữ ba mươi ngày."),
    ("Mật khẩu có 12 ký tự.", "Mật khẩu có mười hai ký tự."),
])
def test_number_words_in_evidence_cover_digit_requirement(requirement, evidence):
    assert missing(requirement, evidence) == []


@pytest.mark.xfail(strict=True, reason=(
    "WRONG DEMOTION (ambiguous by design): sizes are decimal (1 GB = 1000 MB), so 2048 MB / 1024 MB "
    "do not cover 2 GB / 1 GB. Smallest fix: also accept the binary reading (x1024) for KB/MB/GB."))
@pytest.mark.parametrize("requirement,evidence", [
    ("Uploads up to 2 GB.", "Uploads up to 2048 MB."),
    ("Uploads up to 1 GB.", "Uploads up to 1024 MB."),
])
def test_binary_size_equivalence(requirement, evidence):
    assert missing(requirement, evidence) == []
