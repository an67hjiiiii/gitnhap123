# SỔ TAY KỸ SƯ MỚI VÀ QUY CHUẨN LẬP TRÌNH – PAYNHANH

Mã tài liệu: PN-HR-07 · Phiên bản 1.2 · Ngày: 10/11/2026
Dành cho: kỹ sư phần mềm mới gia nhập nhóm Kỹ thuật

## 1. Chào mừng
Chào mừng bạn đến với PayNhanh. Sổ tay này giúp bạn làm việc hiệu quả trong hai tuần đầu: cần đọc gì, hỏi ai, viết mã theo quy chuẩn nào và những điều tuyệt đối không được làm khi làm việc với hệ thống thanh toán.

## 2. Lộ trình hai tuần đầu
| Ngày | Việc cần làm | Người hướng dẫn |
|---|---|---|
| Ngày 1 | Nhận máy, tài khoản, bật xác thực hai lớp; học bảo mật cơ bản | Quản trị hệ thống |
| Ngày 2 | Đọc Đặc tả yêu cầu PN-SRS-01 và Kiến trúc PN-ARC-06 | Trưởng nhóm |
| Ngày 3 | Đọc Thiết kế CSDL PN-DB-02 và Đặc tả API PN-API-03 | Kỹ sư kèm cặp |
| Ngày 4 | Chạy hệ thống trên máy cá nhân; tạo đơn thử trên sandbox | Kỹ sư kèm cặp |
| Ngày 5 | Đọc Chính sách bảo mật PN-SEC-04; làm bài kiểm tra 10 câu | Trưởng nhóm bảo mật |
| Tuần 2 | Sửa một lỗi nhỏ được giao, mở yêu cầu gộp mã đầu tiên | Kỹ sư kèm cặp |
| Cuối tuần 2 | Trực ca cùng kỹ sư chính một ngày để làm quen PN-OPS-05 | Kỹ sư trực |
Kỹ sư mới chưa được cấp quyền truy cập production trong 30 ngày đầu.

## 3. Công cụ
- Mã nguồn: GitLab nội bộ; mỗi dịch vụ một kho.
- Quản lý công việc: bảng Kanban theo sprint 2 tuần.
- Trao đổi: kênh chat nội bộ; không trao đổi dữ liệu khách hàng qua ứng dụng chat cá nhân.
- Bí mật: lấy qua Vault bằng tài khoản cá nhân; không lưu bí mật trong tệp .env được commit.

## 4. Quy chuẩn viết mã Python
- Theo PEP 8, định dạng tự động bằng ruff format; độ dài dòng tối đa 100 ký tự.
- Bắt buộc gợi ý kiểu (type hints) cho hàm công khai; kiểm tra bằng mypy ở chế độ strict cho payment-service và refund-service.
- Tiền là int theo đồng; cấm dùng float cho tiền. Khi cần chia (ví dụ tính phí), dùng Decimal và làm tròn theo quy tắc ghi trong tài liệu phí.
- Thời gian luôn có múi giờ (datetime có tzinfo=UTC); cấm datetime.now() không múi giờ.
- Truy vấn cơ sở dữ liệu qua SQLAlchemy với tham số; cấm f-string ghép SQL.
- Không bắt ngoại lệ chung (except Exception) rồi bỏ qua. Nếu bắt, phải ghi log có request_id và ném lại hoặc trả lỗi rõ ràng.
- Không ghi log thân yêu cầu đầy đủ của API thanh toán; chỉ ghi các trường đã được phép.

## 5. Quy chuẩn kiểm thử
- Mỗi yêu cầu gộp mã có kiểm thử cho thay đổi của mình; độ bao phủ dòng của payment-service không được giảm.
- Bắt buộc có kiểm thử cho: gửi lặp cùng Idempotency-Key, hai yêu cầu hoàn tiền đồng thời, chuyển trạng thái không hợp lệ, truy cập đơn của merchant khác.
- Kiểm thử tích hợp dùng cơ sở dữ liệu PostgreSQL thật trong container, không dùng SQLite thay thế, vì khác biệt về khóa và chỉ mục có điều kiện.

## 6. Quy trình Git
- Nhánh tính năng đặt tên theo mẫu feature/PN-<số việc>-mo-ta-ngan.
- Thông điệp commit theo dạng "loại(phạm vi): mô tả", ví dụ fix(refund): chặn hoàn tiền vượt số đã thanh toán.
- Không đẩy thẳng vào nhánh chính; không tự gộp yêu cầu của chính mình.
- Yêu cầu gộp mã nên dưới 400 dòng thay đổi để người đánh giá đọc kỹ được.

## 7. Đánh giá mã
Người đánh giá kiểm tra theo thứ tự: đúng nghiệp vụ, an toàn tiền (có thể trừ hai lần, hoàn vượt, mất sự kiện không), bảo mật (phân quyền, lộ dữ liệu), kiểm thử, rồi mới đến cách đặt tên và trình bày. Phản hồi lịch sự, nêu lý do, đề xuất cách sửa.

## 8. Mười điều tuyệt đối không làm
1. Không chạy lệnh sửa dữ liệu trực tiếp trên production khi chưa có phiếu thay đổi được duyệt.
2. Không sao chép dữ liệu production về máy cá nhân.
3. Không ghi số thẻ, khóa API, mật khẩu vào log, chat hay tài liệu.
4. Không tắt kiểm tra chữ ký webhook hay chữ ký ngân hàng "để thử cho nhanh".
5. Không dùng tài khoản dùng chung.
6. Không gộp mã khi CI đang đỏ.
7. Không triển khai ngoài khung giờ cho phép, trừ khi đang xử lý SEV-1 và được Người chỉ huy sự cố đồng ý.
8. Không xóa bản ghi giao dịch hay lịch sử trạng thái.
9. Không trả lời yêu cầu cung cấp thông tin khách hàng qua điện thoại hay email chưa xác minh.
10. Không giấu lỗi: phát hiện sai sót thì báo ngay, càng sớm càng ít thiệt hại.

## 9. Hỏi ai khi cần
| Chủ đề | Đầu mối |
|---|---|
| Nghiệp vụ thanh toán, trạng thái đơn | Trưởng nhóm Sản phẩm |
| Cơ sở dữ liệu, hiệu năng truy vấn | Kỹ sư cơ sở dữ liệu |
| Bảo mật, phân quyền, sự cố bảo mật | Trưởng nhóm bảo mật |
| Hạ tầng, triển khai | Nhóm Hạ tầng |
| Đối soát, hoàn tiền lớn | Bộ phận Finance |

## 10. Đánh giá cuối giai đoạn thử việc
Sau 60 ngày, kỹ sư được đánh giá theo: chất lượng mã, tuân thủ quy chuẩn bảo mật, khả năng phối hợp, và mức độ tự xử lý công việc được giao.
