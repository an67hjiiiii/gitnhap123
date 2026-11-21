"""Hậu kiểm câu trả lời ô chat (21/11): máy tính thay phép tính, cảnh báo số không có trong nguồn, dọn rác trình bày."""
from app.core.answer_checks import apply_calc, clean, finish, unsupported_numbers


def test_calc_overtime_example_from_demo():
    # câu sai trong kịch bản demo: 12 triệu, 26 công, 4 giờ ngày thường (150%) + 8 giờ ngày nghỉ (200%)
    out = apply_calc("Tổng = [[= 12.000.000/26/8*4*1,5 + 12000000/26/8*8*2 ]] đồng")
    assert out == "Tổng = **1.269.230,77** đồng"


def test_calc_rejects_code_and_keeps_text():
    assert apply_calc("[[= __import__('os') ]]") == "[[= __import__('os') ]]"  # không khớp mẫu số: để nguyên, không chạy
    assert apply_calc("[[= 2**999999 ]]") == "2**999999"  # lũy thừa không được phép (tránh treo máy)
    assert apply_calc("[[= 1/0 ]]") == "1/0"


def test_unsupported_numbers_flag_invented_retirement_ages():
    evidence = "đủ 62 tuổi đối với lao động nam vào năm 2028 và đủ 60 tuổi đối với lao động nữ vào năm 2035; 03 tháng, 04 tháng"
    answer = "Nam 60 tuổi, nữ 50 tuổi; tăng lên 65 tuổi vào năm 2029. Nam 62 tuổi năm 2028."
    assert unsupported_numbers(answer, evidence) == ["2029", "50", "65"]


def test_numbers_in_calc_and_list_markers_are_not_flagged():
    answer = "1. Lương giờ = [[= 12000000/26/8 ]] đồng\n2. Theo Điều 98 (Bo luat · đoạn 90)"
    assert unsupported_numbers(answer, "Điều 98 lương 150%") == []


def test_finish_cleans_junk_and_warns():
    text, bad = finish("Được nghỉ 12 ngày, sai 99 ngày.\n\n| Mục | Chunk ID |\n|---|---|\n\nCác chunk ID liên quan:\n(src_ab · đoạn 1)", "nghỉ 12 ngày")
    assert "Các chunk ID" not in text and "| Nguồn |" in text
    assert bad == ["99"] and "Cần kiểm tra lại" in text
    assert clean("T1 chỉ ra rằng ngày nghỉ là 12") == "chỉ ra rằng ngày nghỉ là 12"


def test_calc_accepts_model_variants():
    assert apply_calc("[[ 3.000 * 1,5 = 45 ]]") == "**4.500**"
    assert apply_calc("[[= 260000000*(1-0.27) ]]") == "**189.800.000**"
    assert apply_calc("Không phải phép tính [[ghi chú]]") == "Không phải phép tính [[ghi chú]]"


def test_percent_written_as_ratio_is_not_flagged():
    assert unsupported_numbers("Chiết khấu 260.000.000 * 0.22", "giá 260.000.000 đ, chiết khấu 22%") == []


def test_wrong_article_number_is_flagged():
    from app.core.answer_checks import unsupported_articles
    src = "Điều 14. Công nhận tốt nghiệp ... 3. Hạng tốt nghiệp bị giảm đi một mức nếu học lại vượt quá 5%"
    assert unsupported_articles("Theo Điều 3, khoản 5 hạng tốt nghiệp bị giảm; Điều 14 quy định", src) == ["3"]
    text, _ = finish("Bị giảm một mức theo Điều 3.", src)
    assert "Lưu ý căn cứ" in text and "Điều 3" in text


def test_fold_fast_path_matches_per_character_filter():
    """22/11: _fold dùng str.translate thay cho lọc từng ký tự; kết quả phải y hệt."""
    import unicodedata
    from app.analysis.evaluation import _content_tokens, _fold
    ref = lambda t: "".join(c for c in unicodedata.normalize("NFD", t.casefold()) if unicodedata.category(c) != "Mn").replace("đ", "d")
    for t in ["Điều 11. Cảnh báo HỌC TẬP – ĐTB tích lũy dưới 1,2", "Ångström naïve ß ẞ İ", "", "Mỗi người có thể được nghỉ"]:
        assert _fold(t) == ref(t)
    assert _content_tokens("Nhân viên phải gửi đơn trước 03 ngày") == ["nhan", "vien", "gui", "don", "truoc", "03", "ngay"]
