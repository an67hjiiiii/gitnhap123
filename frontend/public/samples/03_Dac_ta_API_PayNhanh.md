# ĐẶC TẢ API TÍCH HỢP – CỔNG THANH TOÁN PAYNHANH

Mã tài liệu: PN-API-03 · Phiên bản 1.2 · Ngày: 06/11/2026
Địa chỉ gốc: https://api.paynhanh.vn/v1 (thật) · https://sandbox.paynhanh.vn/v1 (thử)

## 1. Nguyên tắc chung
- Kiểu REST, dữ liệu JSON mã hóa UTF-8.
- Mọi yêu cầu qua HTTPS với TLS 1.2 trở lên; yêu cầu HTTP thường bị từ chối, không chuyển hướng.
- Phiên bản nằm trong đường dẫn (/v1). Thay đổi không tương thích chỉ xuất hiện ở phiên bản mới; /v1 được hỗ trợ ít nhất 12 tháng sau khi /v2 ra mắt.
- Số tiền là số nguyên theo đồng VND.
- Thời gian theo chuẩn ISO 8601, giờ UTC, ví dụ 2026-11-06T03:15:00Z.

## 2. Xác thực
Mỗi yêu cầu gửi header Authorization: Bearer <khóa bí mật>. Khóa có tiền tố sk_live_ hoặc sk_test_. Khóa chỉ dùng ở máy chủ của merchant, tuyệt đối không nhúng vào ứng dụng di động hay mã JavaScript chạy trên trình duyệt.

Khóa công khai (pk_live_, pk_test_) chỉ dùng để mở trang thanh toán phía trình duyệt, không gọi được API quản lý.

## 3. Giới hạn tần suất
| Nhóm API | Giới hạn |
|---|---|
| Tạo đơn | 100 yêu cầu/giây cho mỗi merchant |
| Tra cứu | 300 yêu cầu/giây |
| Hoàn tiền | 20 yêu cầu/giây |
Vượt giới hạn nhận mã 429 kèm header Retry-After (giây). Header X-RateLimit-Remaining cho biết số yêu cầu còn lại trong cửa sổ hiện tại.

## 4. Danh sách điểm cuối
| Phương thức | Đường dẫn | Mô tả | Vai trò cần |
|---|---|---|---|
| POST | /payments | Tạo đơn thanh toán | Khóa bí mật |
| GET | /payments/{payment_id} | Xem một đơn | Khóa bí mật |
| GET | /payments | Danh sách đơn, có phân trang | Khóa bí mật |
| POST | /payments/{payment_id}/cancel | Hủy đơn đang PENDING | Khóa bí mật |
| POST | /payments/{payment_id}/refunds | Tạo hoàn tiền | Khóa bí mật, quyền Owner |
| GET | /refunds/{refund_id} | Xem hoàn tiền | Khóa bí mật |
| GET | /webhook-deliveries | Lịch sử gửi webhook | Khóa bí mật |
| POST | /webhook-deliveries/{id}/resend | Gửi lại webhook | Khóa bí mật |

## 5. Tạo đơn thanh toán: POST /payments

### Header bắt buộc
- Authorization: Bearer sk_test_...
- Idempotency-Key: chuỗi 16–128 ký tự, khuyến nghị dùng UUID v4 sinh mới cho mỗi đơn hàng.
- Content-Type: application/json

### Thân yêu cầu
```
{
  "merchant_order_id": "DH-2026-001245",
  "amount": 1250000,
  "description": "Thanh toan don hang DH-2026-001245",
  "return_url": "https://shop.vidu.vn/thanh-toan/ket-qua",
  "allowed_methods": ["vietqr", "napas"]
}
```

### Phản hồi 201 Created
```
{
  "payment_id": "pay_8f2kQ1x9LmZ0aB7c",
  "status": "PENDING",
  "amount": 1250000,
  "checkout_url": "https://pay.paynhanh.vn/c/pay_8f2kQ1x9LmZ0aB7c",
  "expires_at": "2026-11-06T03:30:00Z"
}
```

### Hành vi khi gửi lặp
| Tình huống | Kết quả |
|---|---|
| Cùng Idempotency-Key, cùng thân yêu cầu, trong 24 giờ | 200 OK, trả lại đúng đơn cũ, header Idempotent-Replayed: true |
| Cùng Idempotency-Key, thân yêu cầu khác | 409 IDEMPOTENCY_CONFLICT |
| Yêu cầu đầu tiên đang xử lý chưa xong | 409 REQUEST_IN_PROGRESS, merchant thử lại sau 1 giây |
| Không gửi Idempotency-Key | 400 IDEMPOTENCY_KEY_REQUIRED |
| merchant_order_id đã có đơn khác | 409 DUPLICATE_ORDER |

Khuyến nghị cho merchant: khi gặp lỗi mạng hoặc hết thời gian chờ, gửi lại với cùng Idempotency-Key, không sinh key mới. Sinh key mới có thể tạo ra đơn thứ hai.

## 6. Mã lỗi chuẩn
Mọi lỗi có dạng:
```
{ "error": { "code": "AMOUNT_OUT_OF_RANGE", "message": "So tien phai tu 1.000 den 500.000.000 VND", "request_id": "req_..." } }
```
| HTTP | Mã | Ý nghĩa |
|---|---|---|
| 400 | VALIDATION_ERROR | Thiếu trường hoặc sai kiểu |
| 400 | AMOUNT_OUT_OF_RANGE | Số tiền ngoài khoảng cho phép |
| 401 | INVALID_API_KEY | Khóa sai, hết hạn hoặc bị thu hồi |
| 403 | PERMISSION_DENIED | Khóa không đủ quyền cho thao tác |
| 404 | NOT_FOUND | Không có đối tượng hoặc không thuộc merchant này |
| 409 | IDEMPOTENCY_CONFLICT | Trùng key, khác nội dung |
| 409 | INVALID_STATE | Thao tác không hợp lệ với trạng thái hiện tại, ví dụ hủy đơn đã thành công |
| 422 | REFUND_EXCEEDS_AMOUNT | Tổng hoàn vượt số đã thanh toán |
| 429 | RATE_LIMITED | Vượt giới hạn tần suất |
| 500 | INTERNAL_ERROR | Lỗi hệ thống, có request_id để tra cứu |
| 503 | PROVIDER_UNAVAILABLE | Ngân hàng đối tác tạm ngừng |

Lưu ý bảo mật: với đơn thuộc merchant khác, API trả 404 thay vì 403 để không tiết lộ đơn đó tồn tại.

## 7. Hoàn tiền: POST /payments/{payment_id}/refunds
Header Idempotency-Key bắt buộc như tạo đơn.
```
{ "amount": 450000, "reason": "Khach tra lai 1 san pham" }
```
Phản hồi 201 với status REQUESTED (cần duyệt) hoặc PROCESSING (tự động). Hoàn tiền chỉ được phép khi đơn ở SUCCEEDED hoặc PARTIALLY_REFUNDED.

## 8. Webhook gửi đến merchant

### Sự kiện
payment.succeeded, payment.failed, payment.expired, refund.succeeded, refund.failed.

### Định dạng
```
POST https://shop.vidu.vn/webhooks/paynhanh
X-PayNhanh-Event-Id: evt_3Jd9...
X-PayNhanh-Timestamp: 1762399200
X-PayNhanh-Signature: v1=5f1c...e9
{ "type": "payment.succeeded", "data": { "payment_id": "pay_8f2k...", "amount": 1250000, "status": "SUCCEEDED" } }
```

### Cách merchant kiểm tra chữ ký
1. Lấy chuỗi ký = Timestamp + "." + thân yêu cầu nguyên văn (chưa phân tích JSON).
2. Tính HMAC-SHA256 với khóa bí mật webhook (whsec_...).
3. So sánh với giá trị sau "v1=" bằng hàm so sánh thời gian hằng định.
4. Từ chối nếu Timestamp lệch quá 5 phút so với giờ máy chủ, để chống phát lại.
5. Lưu Event-Id đã xử lý; nếu gặp lại thì trả 200 và bỏ qua.

### Gửi lại
Merchant phải trả 2xx trong 10 giây. Nếu không, PayNhanh gửi lại tối đa 8 lần theo lịch 1 phút, 5 phút, 15 phút, 1 giờ, 3 giờ, 6 giờ, 12 giờ, 24 giờ. Sau lần cuối thất bại, endpoint bị đánh dấu lỗi và merchant nhận email cảnh báo.

Merchant nên xử lý nặng (gửi email cho khách, cập nhật kho) ở hàng đợi riêng và trả 200 ngay khi đã ghi nhận sự kiện.

## 9. Phân trang
GET /payments?limit=50&starting_after=pay_... dùng con trỏ, không dùng số trang, để kết quả không bị lệch khi có đơn mới. limit tối đa 100.

## 10. Môi trường thử
- Thẻ thử 9704 0000 0000 0018 luôn thành công; 9704 0000 0000 0026 luôn thất bại do không đủ số dư.
- Mã QR thử tự chuyển sang thành công sau 10 giây.
- Dữ liệu sandbox bị xóa sau 90 ngày.
