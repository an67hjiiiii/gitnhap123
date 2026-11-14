from app.review_adapters.auto_route import choose_path


def test_short_request_routes_to_b():
    choice = choose_path("Mật khẩu phải có ít nhất 12 ký tự.")
    assert (choice.path, choice.reason) == ("B", "SHORT_REQUEST")


def test_multiple_obligations_route_to_c_with_counts():
    choice = choose_path(
        "Vé sự cố phải được giữ 30 ngày và thông báo sự cố phải được gửi qua email và SMS."
    )
    assert choice.path == "C"
    assert choice.reason == "MULTI_IDEA"
    assert choice.params["ideas"] == 3


def test_compound_request_routes_to_c():
    choice = choose_path(
        "Tài khoản phải bị khóa sau 3 lần nhập sai và phiên phải hết hạn sau 30 phút không hoạt động."
    )
    assert choice.path == "C"
    assert choice.reason in {"MULTI_IDEA", "MULTI_QUANTITY"}


def test_unavailable_c_routes_to_b():
    choice = choose_path(
        "Tài khoản phải bị khóa sau 3 lần nhập sai và phiên phải hết hạn sau 30 phút không hoạt động.",
        c_available=False,
    )
    assert choice.path == "B"
    assert choice.reason == "C_NOT_AVAILABLE"


def test_single_long_obligation_routes_to_b():
    choice = choose_path(
        "Hệ thống phải lưu nhật ký kiểm toán của mọi thay đổi vai trò người dùng trong cơ sở dữ liệu riêng biệt."
    )
    assert (choice.path, choice.reason) == ("B", "SINGLE_IDEA")
