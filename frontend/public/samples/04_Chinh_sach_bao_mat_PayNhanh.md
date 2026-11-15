# CHÍNH SÁCH BẢO MẬT THÔNG TIN – PAYNHANH

Mã tài liệu: PN-SEC-04 · Phiên bản 2.0 · Ngày hiệu lực: 01/11/2026
Phạm vi: toàn bộ hệ thống, nhân sự và đối tác có truy cập dữ liệu của Cổng thanh toán PayNhanh

## 1. Mục tiêu
Bảo vệ tính bí mật, toàn vẹn và sẵn sàng của dữ liệu thanh toán; đáp ứng định hướng PCI DSS v4.0, Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân và các yêu cầu của Ngân hàng Nhà nước đối với tổ chức trung gian thanh toán.

## 2. Phân loại dữ liệu
| Mức | Ví dụ | Quy định |
|---|---|---|
| Tuyệt mật | Khóa mã hóa chính, khóa bí mật API dạng gốc, khóa ký webhook | Chỉ nằm trong kho bí mật (Vault); không ghi log; không gửi qua chat hoặc email |
| Mật | Số tài khoản ngân hàng merchant, họ tên và số điện thoại người mua, 6 số đầu và 4 số cuối thẻ | Mã hóa khi lưu; chỉ vai trò được phép mới xem; che khi hiển thị |
| Nội bộ | Tài liệu thiết kế, báo cáo vận hành | Chỉ nhân viên PayNhanh |
| Công khai | Tài liệu API, bảng giá | Không hạn chế |

Số thẻ đầy đủ, ngày hết hạn và CVV không bao giờ được lưu, ghi log hay hiển thị. Việc nhập thẻ diễn ra trên trang của ngân hàng hoặc của nhà cung cấp đã đạt PCI DSS.

## 3. Kiểm soát truy cập
### 3.1 Nguyên tắc
- Quyền tối thiểu: mỗi người, mỗi dịch vụ chỉ có quyền cần cho công việc.
- Tách nhiệm vụ: người viết mã không tự duyệt triển khai lên môi trường thật; người tạo yêu cầu hoàn tiền lớn không tự duyệt.
- Rà soát quyền mỗi quý; thu hồi quyền trong 24 giờ khi nhân viên nghỉ việc hoặc đổi vị trí.

### 3.2 Phân quyền theo vai trò (RBAC)
| Thao tác | Owner | Staff | Operator | Finance | Admin |
|---|---|---|---|---|---|
| Xem đơn của merchant mình | Có | Có | Có (khi hỗ trợ) | Có | Không |
| Tạo hoặc thu hồi khóa API | Có | Không | Không | Không | Không |
| Tạo hoàn tiền | Có | Không | Không | Không | Không |
| Duyệt hoàn tiền từ 10 triệu | Không | Không | Không | Có | Không |
| Xem nhật ký kiểm toán | Của mình | Không | Có | Có | Có |
| Đổi vai trò người dùng nội bộ | Không | Không | Không | Không | Có |

Mọi kiểm tra quyền thực hiện ở máy chủ cho từng yêu cầu. Truy vấn dữ liệu luôn kèm điều kiện merchant_id lấy từ phiên đăng nhập hoặc khóa API, không lấy từ tham số do người dùng gửi lên, nhằm chống lỗi truy cập đối tượng của người khác (IDOR/BOLA).

### 3.3 Xác thực
- Nhân viên nội bộ: đăng nhập một lần qua nhà cung cấp danh tính của công ty, bắt buộc xác thực hai lớp bằng ứng dụng hoặc khóa bảo mật phần cứng.
- Merchant: mật khẩu tối thiểu 12 ký tự, kiểm tra với danh sách mật khẩu đã lộ; khuyến nghị bật xác thực hai lớp, bắt buộc với Owner khi bật môi trường thật.
- Khóa tài khoản 15 phút sau 5 lần đăng nhập sai liên tiếp.
- Phiên đăng nhập web hết hạn sau 30 phút không hoạt động; cookie có thuộc tính HttpOnly, Secure, SameSite=Lax.

## 4. Bảo vệ API
- Khóa API lưu dạng băm SHA-256 kèm tiền tố để tra cứu; không thể khôi phục khóa gốc.
- Giới hạn tần suất theo merchant và theo địa chỉ IP (xem PN-API-03 mục 3).
- Kiểm tra đầu vào bằng lược đồ chặt; từ chối trường lạ; giới hạn kích thước thân yêu cầu 64 KB.
- Truy vấn cơ sở dữ liệu luôn dùng tham số hóa, cấm ghép chuỗi SQL.
- Trả 404 cho đối tượng không thuộc merchant gọi API.
- Header bảo mật trên trang thanh toán: Content-Security-Policy, Strict-Transport-Security, X-Frame-Options DENY.
- Webhook ký bằng HMAC-SHA256 kèm dấu thời gian; khuyến nghị merchant từ chối thông báo lệch quá 5 phút.
- URL webhook do merchant khai báo phải là HTTPS và không được trỏ về địa chỉ nội bộ (127.0.0.0/8, 10.0.0.0/8, 169.254.0.0/16...) để chống tấn công SSRF.

## 5. Mã hóa và quản lý khóa
- Truyền tải: TLS 1.2 trở lên, ưu tiên TLS 1.3; tắt các bộ mã yếu.
- Lưu trữ: AES-256-GCM cho cột dữ liệu Mật; ổ đĩa máy chủ cơ sở dữ liệu được mã hóa toàn phần.
- Khóa mã hóa dữ liệu được bọc bởi khóa chính trong Vault; xoay vòng khóa mỗi 12 tháng hoặc ngay khi nghi lộ.
- Khóa ký webhook của merchant có thể được merchant tự xoay; khóa cũ còn hiệu lực song song 24 giờ.

## 6. Ghi nhật ký và giám sát
- Ghi nhật ký kiểm toán cho mọi thao tác nhạy cảm (xem PN-DB-02 mục 3.7), lưu 5 năm, không sửa được.
- Nhật ký ứng dụng không chứa mật khẩu, khóa, token, số tài khoản đầy đủ; bộ lọc tự động che các mẫu này trước khi ghi.
- Cảnh báo theo thời gian thực khi: tỷ lệ đăng nhập sai tăng đột biến, một khóa API gọi từ quốc gia mới, hoàn tiền vượt 50 triệu trong một giờ cho cùng merchant, có giao dịch thành công thứ hai cho cùng đơn.

## 7. Phát triển phần mềm an toàn
- Mọi thay đổi mã qua đánh giá của ít nhất một người khác trước khi gộp.
- Quét phụ thuộc và quét mã tĩnh tự động trong quy trình CI; lỗi mức Cao chặn việc gộp.
- Bí mật không được nằm trong mã nguồn; công cụ quét bí mật chạy trên mỗi lần đẩy mã.
- Kiểm thử xâm nhập bởi đơn vị độc lập trước khi phát hành chính thức và mỗi năm một lần.
- Kiểm tra theo danh mục OWASP ASVS mức 2 cho các chức năng xác thực, phân quyền, quản lý phiên.

## 8. Xử lý sự cố bảo mật
| Mức | Ví dụ | Thời gian phản hồi | Báo cáo |
|---|---|---|---|
| Nghiêm trọng | Lộ dữ liệu người mua, khóa bí mật bị lộ | 15 phút | Giám đốc, ngân hàng đối tác trong 24 giờ; cơ quan chức năng theo luật trong 72 giờ |
| Cao | Tài khoản Operator bị chiếm | 1 giờ | Giám đốc Kỹ thuật |
| Trung bình | Lỗ hổng chưa bị khai thác | 1 ngày làm việc | Trưởng nhóm bảo mật |

Quy trình: phát hiện → cô lập (thu hồi khóa, khóa tài khoản) → điều tra → khắc phục → thông báo → rút kinh nghiệm trong 5 ngày làm việc.

## 9. Đối tác và nhà cung cấp
Nhà cung cấp có truy cập dữ liệu phải ký thỏa thuận bảo mật, chứng minh biện pháp bảo vệ tương đương và được đánh giá lại hằng năm.

## 10. Đào tạo
Nhân viên mới học bảo mật cơ bản trong tuần đầu. Toàn bộ nhân viên học lại mỗi năm và tham gia ít nhất một bài diễn tập lừa đảo qua email.
