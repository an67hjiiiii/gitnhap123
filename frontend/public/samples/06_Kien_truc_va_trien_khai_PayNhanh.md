# KIẾN TRÚC HỆ THỐNG VÀ HẠ TẦNG TRIỂN KHAI – PAYNHANH

Mã tài liệu: PN-ARC-06 · Phiên bản 1.0 · Ngày: 09/11/2026

## 1. Tổng quan kiến trúc
Hệ thống gồm các dịch vụ tách biệt, giao tiếp qua HTTP nội bộ và hàng đợi tin nhắn:
| Dịch vụ | Nhiệm vụ | Công nghệ |
|---|---|---|
| api-gateway | Nhận yêu cầu từ merchant, xác thực khóa API, giới hạn tần suất | Nginx + mô-đun Lua |
| payment-service | Tạo đơn, quản lý trạng thái, chống trùng | Python FastAPI |
| provider-adapter | Kết nối ngân hàng, ví, VietQR | Python, một mô-đun cho mỗi đối tác |
| webhook-service | Gửi và gửi lại webhook | Python, đọc hàng đợi |
| refund-service | Xử lý hoàn tiền và luồng duyệt | Python FastAPI |
| reconciliation-job | Đối soát cuối ngày | Tác vụ định kỳ |
| merchant-dashboard | Giao diện cho merchant | React |
| back-office | Giao diện cho Operator, Finance | React |

Cơ sở dữ liệu PostgreSQL 16 (một máy chủ chính, một bản sao đồng bộ cùng vùng, một bản sao đọc). Hàng đợi RabbitMQ cho sự kiện thay đổi trạng thái. Redis cho bộ đếm giới hạn tần suất và bộ nhớ đệm ngắn hạn, không dùng Redis làm nơi lưu idempotency chính.

## 2. Luồng tạo đơn và thanh toán
1. Merchant gọi POST /payments qua api-gateway.
2. api-gateway kiểm tra khóa API, giới hạn tần suất, chuyển yêu cầu kèm merchant_id đã xác thực.
3. payment-service ghi idempotency_records và payments trong một giao dịch cơ sở dữ liệu, trả checkout_url.
4. Người mua mở checkout_url, chọn phương thức; provider-adapter gọi ngân hàng.
5. Ngân hàng gọi lại provider-adapter; adapter xác minh chữ ký của ngân hàng rồi gửi sự kiện vào hàng đợi.
6. payment-service cập nhật trạng thái đơn, ghi payment_status_history, phát sự kiện payment.succeeded.
7. webhook-service nhận sự kiện, ký HMAC và gửi đến merchant.

Mẫu "outbox": sự kiện được ghi vào bảng outbox trong cùng giao dịch với việc cập nhật trạng thái, sau đó một tiến trình riêng đọc bảng outbox và đẩy vào RabbitMQ. Cách này bảo đảm không có tình huống trạng thái đã đổi mà sự kiện bị mất.

## 3. Môi trường
| Môi trường | Mục đích | Dữ liệu |
|---|---|---|
| dev | Lập trình viên thử nghiệm | Dữ liệu giả |
| staging | Kiểm thử tích hợp, giống thật | Dữ liệu giả, kết nối sandbox ngân hàng |
| sandbox | Merchant thử tích hợp | Dữ liệu của merchant, không có tiền thật |
| production | Vận hành thật | Dữ liệu thật |
Không sao chép dữ liệu production sang môi trường khác.

## 4. Hạ tầng
- Chạy trên Kubernetes, mỗi dịch vụ tối thiểu 3 bản sao trải trên 3 vùng khả dụng.
- Tự mở rộng theo CPU và độ dài hàng đợi; webhook-service mở rộng khi hàng đợi trên 1.000 tin.
- Mạng nội bộ chia vùng: chỉ api-gateway và trang thanh toán có địa chỉ công khai; cơ sở dữ liệu chỉ nhận kết nối từ các dịch vụ trong cùng vùng mạng riêng.
- Kết nối ra ngân hàng đi qua địa chỉ IP cố định đã đăng ký với ngân hàng.

## 5. Quy trình CI/CD
1. Lập trình viên mở yêu cầu gộp mã; CI chạy kiểm thử đơn vị, kiểm tra kiểu, quét bảo mật, quét bí mật.
2. Ít nhất một người đánh giá phê duyệt.
3. Gộp vào nhánh chính tự động triển khai lên staging và chạy kiểm thử tích hợp với sandbox ngân hàng.
4. Triển khai production cần phê duyệt của người không phải tác giả, theo khung giờ trong PN-OPS-05 mục 7.
5. Mỗi ảnh container được ký và quét lỗ hổng; chỉ ảnh đã ký mới được chạy trên production.

## 6. Quan sát hệ thống
- Nhật ký có cấu trúc dạng JSON, mỗi yêu cầu có request_id xuyên suốt các dịch vụ.
- Chỉ số theo chuẩn Prometheus; bảng theo dõi Grafana cho từng dịch vụ.
- Truy vết phân tán bằng OpenTelemetry để xem một đơn đi qua những dịch vụ nào và tốn bao lâu ở mỗi bước.

## 7. Kế hoạch dung lượng
Mục tiêu năm đầu: 2 triệu đơn mỗi tháng, đỉnh 200 yêu cầu tạo đơn mỗi giây vào các ngày khuyến mãi. Đây là con số kế hoạch, cần kiểm chứng bằng kiểm thử tải trước khi phát hành chính thức.

## 8. Rủi ro kỹ thuật đã biết
| Rủi ro | Biện pháp |
|---|---|
| Ngân hàng gọi lại trùng nhiều lần | Chỉ mục duy nhất trên provider_reference; xử lý gọi lại theo kiểu bỏ qua nếu đã có |
| Hàng đợi tắc khi merchant lớn lỗi webhook | Hàng đợi riêng theo merchant, giới hạn số lần gửi đồng thời mỗi merchant |
| Đồng hồ các máy lệch nhau | Đồng bộ NTP; dùng thời gian của cơ sở dữ liệu cho các mốc nghiệp vụ |
| Phụ thuộc một ngân hàng VietQR | Ký với ngân hàng dự phòng thứ hai trước M3 |
