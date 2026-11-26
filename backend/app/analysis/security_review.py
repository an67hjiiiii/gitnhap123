"""Rà soát bảo mật theo danh mục chọn lọc từ OWASP ASVS 4.0.3.

Mỗi tiêu chí được kiểm tra như một yêu cầu trong chức năng truy vết, nhưng luôn giao cho tác tử Bảo mật:
truy xuất đoạn tài liệu liên quan, kết luận Đạt / Đạt một phần / Chưa thấy biện pháp kèm trích dẫn.
Đây là danh mục rút gọn để rà soát tài liệu thiết kế, không thay thế đánh giá chứng nhận ASVS đầy đủ.
"""

from __future__ import annotations

from app.analysis.traceability import Requirement
from app.research.registry import profile

ASVS_VERSION = "OWASP ASVS 4.0.3"

# (mã ASVS, nhóm, tiêu chí, mô tả kèm từ khóa để truy xuất đoạn tài liệu tiếng Việt lẫn tiếng Anh)
_CONTROLS: tuple[tuple[str, str, str, str], ...] = (
    ("V2.1.1", "Xác thực", "Mật khẩu người dùng dài tối thiểu 12 ký tự",
     "Mật khẩu do người dùng đặt phải có độ dài tối thiểu 12 ký tự. password minimum length"),
    ("V2.1.7", "Xác thực", "Kiểm tra mật khẩu với danh sách mật khẩu đã bị lộ",
     "Khi đăng ký, đăng nhập và đổi mật khẩu, mật khẩu được kiểm tra với danh sách mật khẩu đã bị lộ. breached passwords"),
    ("V2.2.1", "Xác thực", "Chống dò mật khẩu và tấn công tự động",
     "Có biện pháp chống tự động hóa: giới hạn số lần đăng nhập sai, khóa tài khoản tạm thời, chống brute force, rate limit đăng nhập."),
    ("V2.4.1", "Xác thực", "Mật khẩu lưu dạng băm có salt bằng thuật toán chuyên dụng",
     "Mật khẩu được lưu dưới dạng băm có salt bằng hàm băm mật khẩu được phê duyệt (bcrypt, scrypt, Argon2, PBKDF2), không lưu mật khẩu gốc."),
    ("V3.2.1", "Quản lý phiên", "Tạo mã phiên mới sau khi đăng nhập",
     "Ứng dụng tạo session token mới khi người dùng đăng nhập thành công để chống cố định phiên (session fixation)."),
    ("V3.3.1", "Quản lý phiên", "Đăng xuất và hết hạn làm mất hiệu lực phiên",
     "Đăng xuất hoặc phiên hết hạn phải làm mất hiệu lực session token; không dùng lại được phiên cũ. logout invalidate session"),
    ("V3.3.2", "Quản lý phiên", "Hết hạn phiên khi không hoạt động và xác thực lại định kỳ",
     "Phiên đăng nhập hết hạn sau một khoảng thời gian không hoạt động (idle timeout) và yêu cầu xác thực lại định kỳ."),
    ("V3.4.1", "Quản lý phiên", "Cookie phiên có thuộc tính Secure",
     "Cookie chứa session token đặt thuộc tính Secure, chỉ gửi qua HTTPS."),
    ("V3.4.2", "Quản lý phiên", "Cookie phiên có thuộc tính HttpOnly",
     "Cookie chứa session token đặt thuộc tính HttpOnly để JavaScript không đọc được."),
    ("V3.4.3", "Quản lý phiên", "Cookie phiên có thuộc tính SameSite",
     "Cookie chứa session token đặt thuộc tính SameSite (Lax hoặc Strict) để giảm nguy cơ CSRF."),
    ("V4.1.1", "Kiểm soát truy cập", "Kiểm tra quyền ở phía máy chủ",
     "Quy tắc phân quyền được thực thi ở máy chủ cho từng yêu cầu, không dựa vào việc ẩn nút trên giao diện. server-side access control"),
    ("V4.1.3", "Kiểm soát truy cập", "Áp dụng nguyên tắc quyền tối thiểu",
     "Mỗi người dùng và dịch vụ chỉ có quyền tối thiểu cần cho công việc (least privilege); phân quyền theo vai trò RBAC."),
    ("V4.2.1", "Kiểm soát truy cập", "Chống truy cập trái phép đối tượng của người khác (IDOR)",
     "Dữ liệu và API nhạy cảm được bảo vệ chống IDOR/BOLA: truy vấn luôn lọc theo chủ sở hữu, không tin mã đối tượng do người dùng gửi."),
    ("V4.3.1", "Kiểm soát truy cập", "Giao diện quản trị dùng xác thực nhiều lớp",
     "Giao diện quản trị và tài khoản nội bộ dùng xác thực nhiều lớp (MFA, xác thực hai lớp) để chống truy cập trái phép."),
    ("V5.1.3", "Kiểm tra đầu vào", "Kiểm tra mọi đầu vào theo danh sách cho phép",
     "Mọi đầu vào (form, REST request, tham số URL, header) được kiểm tra theo lược đồ và danh sách cho phép (allow list); từ chối trường lạ."),
    ("V5.3.4", "Kiểm tra đầu vào", "Dùng truy vấn tham số hóa để chống SQL injection",
     "Truy vấn cơ sở dữ liệu dùng tham số hóa hoặc ORM, cấm ghép chuỗi SQL, để chống SQL injection."),
    ("V6.2.2", "Mật mã", "Dùng thuật toán mã hóa đã được kiểm chứng",
     "Dùng thuật toán, chế độ và thư viện mật mã đã được kiểm chứng (ví dụ AES-256-GCM, SHA-256, HMAC-SHA256), không tự chế thuật toán."),
    ("V6.4.1", "Mật mã", "Quản lý khóa và bí mật bằng kho bí mật",
     "Khóa mã hóa và bí mật được tạo, lưu, kiểm soát truy cập và hủy bằng giải pháp quản lý bí mật như key vault; có xoay vòng khóa."),
    ("V7.1.1", "Nhật ký và lỗi", "Không ghi mật khẩu, khóa hoặc thông tin thanh toán vào nhật ký",
     "Nhật ký không chứa thông tin đăng nhập, mật khẩu, token, khóa hay số thẻ; dữ liệu nhạy cảm được che trước khi ghi log."),
    ("V7.2.1", "Nhật ký và lỗi", "Ghi nhật ký mọi quyết định xác thực",
     "Mọi lần đăng nhập thành công, thất bại và quyết định xác thực được ghi nhật ký kiểm toán (audit log)."),
    ("V7.3.3", "Nhật ký và lỗi", "Nhật ký bảo mật được bảo vệ khỏi sửa đổi trái phép",
     "Nhật ký kiểm toán được bảo vệ khỏi truy cập và sửa đổi trái phép: chỉ thêm, không sửa, có chuỗi băm, phân quyền xem log."),
    ("V7.4.1", "Nhật ký và lỗi", "Thông báo lỗi chung chung, có mã tra cứu",
     "Khi lỗi bất ngờ, người dùng chỉ thấy thông báo chung kèm mã tra cứu (request_id), không lộ chi tiết hệ thống."),
    ("V8.3.1", "Bảo vệ dữ liệu", "Không đặt dữ liệu nhạy cảm trong tham số URL",
     "Dữ liệu nhạy cảm gửi trong thân yêu cầu hoặc header, không nằm trong query string của URL."),
    ("V8.3.4", "Bảo vệ dữ liệu", "Phân loại dữ liệu nhạy cảm và có chính sách xử lý",
     "Toàn bộ dữ liệu nhạy cảm đã được xác định, phân loại và có chính sách xử lý, mã hóa, che dữ liệu."),
    ("V9.1.1", "Truyền tải", "Mọi kết nối dùng TLS",
     "Mọi kết nối từ client dùng TLS (HTTPS), không quay về kết nối không mã hóa; yêu cầu HTTP thường bị từ chối."),
    ("V9.1.3", "Truyền tải", "Chỉ dùng TLS 1.2 hoặc 1.3",
     "Chỉ bật các phiên bản TLS 1.2 và TLS 1.3, tắt phiên bản và bộ mã yếu."),
    ("V11.1.4", "Logic nghiệp vụ", "Giới hạn tần suất chống lạm dụng nghiệp vụ",
     "Có giới hạn tần suất (rate limit) chống gọi quá mức, rút dữ liệu hàng loạt, lạm dụng nghiệp vụ hoặc từ chối dịch vụ."),
    ("V12.6.1", "Tài nguyên và SSRF", "Chống SSRF bằng danh sách đích được phép",
     "Máy chủ chỉ gửi yêu cầu ra các đích trong danh sách cho phép; chặn địa chỉ nội bộ để chống SSRF (ví dụ URL webhook)."),
    ("V13.1.3", "API", "URL của API không chứa khóa hay token",
     "Đường dẫn API không lộ thông tin nhạy cảm như API key hay session token; khóa gửi trong header Authorization."),
    ("V14.4.3", "Cấu hình", "Có Content-Security-Policy",
     "Phản hồi có header Content-Security-Policy (CSP) để giảm tác động của XSS."),
    ("V14.4.5", "Cấu hình", "Có Strict-Transport-Security (HSTS)",
     "Phản hồi có header Strict-Transport-Security (HSTS) buộc trình duyệt dùng HTTPS."),
    ("V14.4.7", "Cấu hình", "Chống nhúng trang (clickjacking)",
     "Có header X-Frame-Options DENY hoặc CSP frame-ancestors để chống clickjacking."),
)


def asvs_controls() -> list[dict]:
    """Danh mục tiêu chí OWASP ASVS, giao cho chuyên gia Phần mềm & CNTT (hoặc security ở pack cũ)."""
    from app.research.registry import active_pack
    agent_id = "security" if "security" in active_pack()["agents"] else ("software" if "software" in active_pack()["agents"] else active_pack()["default_domain"])
    name = profile(agent_id)["name"]
    return [
        {**Requirement(cid, title, body, [agent_id], agent_id).to_dict(), "group": group, "agent_name": name}
        for cid, group, title, body in _CONTROLS
    ]


# Thuật ngữ cốt lõi phải có trong đoạn được trích thì mới giữ kết luận "Đạt" (đã bỏ dấu, chữ thường).
# Mỗi nhóm là các cách nói tương đương; mọi nhóm của một tiêu chí đều phải khớp.
EVIDENCE_TERMS: dict[str, list[list[str]]] = {
    "V2.1.1": [["mat khau", "password"]],
    "V2.1.7": [["mat khau da lo", "da bi lo", "breach", "breached", "pwned"]],
    "V2.2.1": [["khoa tai khoan", "sai lien tiep", "brute force", "rate limit", "gioi han so lan", "chong tu dong"]],
    "V2.4.1": [["bam", "hash", "bcrypt", "argon2", "pbkdf2", "scrypt"], ["mat khau", "password"]],
    "V3.2.1": [["phien moi", "session token moi", "tao lai phien", "regenerate", "session fixation", "co dinh phien", "doi ma phien"]],
    "V3.3.1": [["dang xuat", "logout", "log out", "vo hieu hoa phien", "thu hoi phien"]],
    "V3.3.2": [["khong hoat dong", "idle", "timeout"]],
    "V3.4.1": [["secure"]],
    "V3.4.2": [["httponly"]],
    "V3.4.3": [["samesite"]],
    "V4.1.1": [["may chu", "server", "server-side"]],
    "V4.1.3": [["quyen toi thieu", "least privilege"]],
    "V4.2.1": [["idor", "bola", "merchant_id", "chu so huu", "404"]],
    "V4.3.1": [["hai lop", "2fa", "mfa", "nhieu lop", "multi-factor"]],
    "V5.1.3": [["luoc do", "schema", "allow list", "danh sach cho phep", "truong la", "validation"]],
    "V5.3.4": [["tham so hoa", "parameterized", "orm", "ghep chuoi", "sqlalchemy", "prepared statement"]],
    "V6.2.2": [["aes", "sha-256", "sha256", "hmac", "tls"]],
    "V6.4.1": [["vault", "kho bi mat", "key vault", "secrets manager"]],
    "V7.1.1": [["log", "nhat ky"], ["mat khau", "khoa", "token", "so the"]],
    "V7.2.1": [["dang nhap", "login", "xac thuc"], ["nhat ky", "log"]],
    "V7.3.3": [["khong sua", "khong cho phep sua", "chuoi bam", "chi them", "append-only", "immutable"]],
    "V7.4.1": [["request_id", "ma tra cuu", "thong bao chung", "generic"]],
    "V8.3.1": [["query string", "tham so url", "tren url", "trong url"]],
    "V8.3.4": [["phan loai du lieu", "du lieu nhay cam", "tuyet mat", "classification"]],
    "V9.1.1": [["tls", "https"]],
    "V9.1.3": [["tls 1.2", "tls 1.3"]],
    "V11.1.4": [["gioi han tan suat", "rate limit", "429"]],
    "V12.6.1": [["ssrf", "dia chi noi bo", "127.0.0.0", "10.0.0.0", "allow list", "danh sach cho phep"]],
    "V13.1.3": [["authorization", "header"], ["khoa", "key", "token"]],
    "V14.4.3": [["content-security-policy", "csp"]],
    "V14.4.5": [["strict-transport-security", "hsts"]],
    "V14.4.7": [["x-frame-options", "frame-ancestors"]],
}
