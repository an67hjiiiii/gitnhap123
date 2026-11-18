"""A6: diff_intent không được kích hoạt bởi từ thường ("bãi bỏ", "so với năm trước", "mở mới", "thêm nữa").

Sáu câu đầu là câu DEV từng bị đẩy nhầm vào đường version_diffs (NO_EVIDENCE/PARTIAL). Các câu còn lại là
câu dựng tay: phải GIỮ ý định đúng (hỏi thay đổi giữa hai phiên bản).
"""
import unicodedata

import pytest

from app.ingestion.version_diff import diff_intent

NOT_VERSION = [
    "Vậy Thông tư 20/2026/TT-BGDĐT bắt đầu có hiệu lực từ ngày nào và bãi bỏ những văn bản nào?",
    "Tiêu chuẩn trình độ hiệu trưởng trường cao đẳng khác gì hiệu trưởng trường trung cấp, với lại Thông tư 17/2026/TT-BGDĐT có hiệu lực từ ngày nào và bãi bỏ điều khoản nào của Thông tư 14/2021 và 15/2021?",
    "Thông tư 17/2026/TT-BGDĐT bãi bỏ các điều khoản nào của Thông tư 14/2021/TT-BLĐTBXH và Thông tư 15/2021/TT-BLĐTBXH về điều lệ trường trung cấp, cao đẳng, và việc chuyển tiếp đối với phó hiệu trưởng đang giữ chức vụ chưa đạt chuẩn trình độ được giải quyết thế nào?",
    "Kể hết tất cả các trường hợp cơ sở đào tạo không được tăng số lượng tuyển sinh so với năm trước liền kề theo Khoản 6 Điều 5 Thông tư 34/2026/TT-BGDĐT.",
    "Ngành đại học mở mới năm đầu được tuyển tối đa bao nhiêu phần trăm năng lực đào tạo của chính ngành đó, còn tổng chỉ tiêu hằng năm của trường bình thường không được tăng quá mấy phần trăm so với số thực tuyển năm trước?",
    "So sánh quy định áp dụng đối với ngành mở mới trong năm tuyển sinh với cơ sở đào tạo mới thành lập trong 05 năm theo Thông tư 34/2026/TT-BGDĐT về việc giới hạn tăng 10% chỉ tiêu và các điều kiện không được tăng chỉ tiêu."
]


@pytest.mark.parametrize("query", NOT_VERSION)
def test_dev_false_diff_triggers_are_normal_questions(query):
    assert diff_intent(query) is None
    assert diff_intent(unicodedata.normalize("NFD", query.upper())) is None


@pytest.mark.parametrize("query", [
    "Thông tư này bãi bỏ những văn bản nào?",
    "Chỉ tiêu được tăng tối đa bao nhiêu so với năm trước liền kề?",
    "Ngành mở mới năm đầu được tuyển bao nhiêu?",
    "Cơ sở mới thành lập trong 5 năm có bị giới hạn không?",
    "Cơ sở đào tạo mới được thành lập cần điều kiện gì?",
    "Thêm nữa, hồ sơ cần những giấy tờ nào?",
    "So sánh quy định đối với ngành A với ngành B theo Thông tư 34/2026/TT-BGDĐT.",
    "Điều 5 khác gì Điều 6 trong Thông tư 17/2026/TT-BGDĐT?",
])
def test_ordinary_questions_do_not_use_diff_route(query):
    assert diff_intent(query) is None


@pytest.mark.parametrize("query,intent", [
    ("So sánh hai bản", "ALL"),
    ("So sánh phiên bản cũ và mới của chính sách mật khẩu", "ALL"),
    ("Thông tư 20/2026 thay đổi gì so với bản trước?", "ALL"),
    ("Có thay đổi không?", "ALL"),
    ("Thời gian mở khóa có thay đổi không?", "ALL"),
    ("Khác nhau thế nào giữa bản cũ và bản mới?", "ALL"),
    ("Điểm mới trong chính sách", "THEM"),
    ("Bản mới thêm điều nào?", "THEM"),
    ("Mục nào bị bỏ ở bản mới?", "ALL"),
    ("Bỏ điều gì?", "BO"),
    ("Có gì mới?", "NEW"),
    ("Thêm và bỏ những gì?", "ALL"),
])
def test_real_version_questions_keep_intent(query, intent):
    assert diff_intent(query) == intent


from app.ingestion.version_diff import mentions_doc_number


@pytest.mark.parametrize("query,numbers,expected", [
    ("Điều 4 của Thông tư 50/2026/TT-BGDĐT thay đổi gì so với Thông tư 25/2021/TT-BGDĐT?", ["25/2021/TT-BGDĐT", "50/2026/TT-BGDĐT"], True),
    ("Thông tư 25/2021 quy định gì?", ["25/2021/TT-BGDĐT"], True),
    ("Điều 5 khoản 7 Thông tư 34/2026/TT-BGDĐT quy định gì?", ["25/2021/TT-BGDĐT", "50/2026/TT-BGDĐT"], False),
    ("Thông tư 150/2026 quy định gì?", ["50/2026/TT-BGDĐT"], False),
    ("Chính sách mật khẩu thay đổi gì?", ["CS-DN-01"], False),
    ("Thông tư 50/2026/TT-BGDĐT thay đổi gì?", [None, ""], False),
])
def test_mentions_doc_number_both_sides(query, numbers, expected):
    assert mentions_doc_number(query, numbers) is expected


from app.ingestion.version_diff import topic_units


def _unit(article, before, after):
    return {"old_article": article, "new_article": article, "old_clause": "1", "new_clause": "1",
            "text_before": before, "text_after": after, "kind": "DOI"}


UNITS = [
    _unit("Điều 24", "Điều khoản chuyển tiếp Thông tư này áp dụng cho khóa đã tuyển sinh trước ngày Thông tư này có hiệu lực",
          "Điều khoản chuyển tiếp Thông tư này áp dụng cho khóa tuyển sinh trước khi Thông tư này có hiệu lực thi hành"),
    _unit("Điều 2", "Giải thích từ ngữ Giảng viên cơ hữu là giảng viên của cơ sở cử đi",
          "Giải thích từ ngữ Giảng viên cơ hữu là nhà giáo được tuyển dụng toàn thời gian"),
]


def test_topic_ignores_document_numbers_and_generic_words():
    q = "Khái niệm giảng viên cơ hữu trong bản mới (Thông tư 50/2026/TT-BGDĐT) thay đổi gì so với bản cũ Thông tư 25/2021/TT-BGDĐT?"
    assert [u["old_article"] for u in topic_units(q, UNITS)] == ["Điều 2"]


def test_no_topic_beyond_document_numbers_keeps_all_units():
    assert topic_units("Thông tư 50/2026/TT-BGDĐT thay đổi gì so với bản cũ Thông tư 25/2021/TT-BGDĐT?", UNITS) == UNITS


from app.core.types import SourceChunk
from app.ingestion.version_diff import is_atomic, rank_diff_rows, shorten_diff_text
from app.research.version_table import build_table


def test_rank_puts_topic_row_first_and_no_topic_keeps_all():
    rows = [{"text_before": "Điều khoản chuyển tiếp Thông tư này áp dụng", "text_after": "Điều khoản chuyển tiếp áp dụng khóa mới"},
            {"text_before": "Giảng viên cơ hữu là giảng viên của cơ sở cử đi", "text_after": "Giảng viên cơ hữu là nhà giáo toàn thời gian"}]
    has_topic, ranked = rank_diff_rows("Giảng viên cơ hữu thay đổi gì so với bản cũ?", rows)
    assert has_topic and ranked[0][1] is rows[1] and ranked[0][0] > ranked[1][0]
    has_topic, ranked = rank_diff_rows("Thông tư 50/2026/TT-BGDĐT thay đổi gì so với bản cũ?", rows)
    assert not has_topic and [r for _, r in ranked] == rows


def test_shorten_and_atomic():
    table = "Phụ lục STT Họ và tên Ngày sinh " * 40
    assert shorten_diff_text(table, "Điều 16").startswith("[bảng/phụ lục thay đổi, xem Điều 16")
    assert len(shorten_diff_text("a " * 600)) <= 452
    assert shorten_diff_text("ngắn") == "ngắn"
    assert is_atomic("tối thiểu 12 ký tự") and is_atomic("phải có") and not is_atomic("Giải thích từ ngữ chung")


def test_build_table_from_provenance_only():
    chunk = SourceChunk("c1", "s1", "doc", "text", 0, provenance={
        "version_diff": True, "diff_kind": "DOI", "diff_old_label": "25/2021", "diff_new_label": "50/2026",
        "diff_old_unit": ("Điều 2", "3"), "diff_new_unit": ("Điều 2", "3"), "diff_before": "cũ | x", "diff_after": "mới"})
    table = build_table([chunk])
    assert table.splitlines()[0] == "| Cũ | Mới | Thay đổi | Nguồn |"
    assert "cũ / x" in table and "Đổi" in table and "25/2021 Điều 2 khoản 3 → 50/2026 Điều 2 khoản 3" in table
    assert build_table([SourceChunk("c2", "s1", "doc", "t", 0)]) == ""
