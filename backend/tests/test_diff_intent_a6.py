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
