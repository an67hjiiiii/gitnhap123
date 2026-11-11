# Đặc Tả Kỹ Thuật REST API Cổng Thanh Toán (Nhóm C1SE.27)

## POST /api/v1/payments/process
Xử lý trừ tiền khách hàng với cơ chế Idempotency nghiêm ngặt và Khóa lạc quan (Optimistic Locking).

### Tiêu Đề Yêu Cầu (Request Headers)
- `Authorization`: Bearer `<JWT_TOKEN>`
- `X-Idempotency-Key`: Chuỗi UUIDv4 bắt buộc chống gửi trùng lặp
- `Content-Type`: application/json

### Cấu Trúc Thân Yêu Cầu (Request Body Schema)
```json
{
  "account_id": "a9b1c2d3-1234-5678-90ab-cdef12345678",
  "amount": 250000,
  "currency": "VND",
  "payment_method": "stripe_card"
}
```

### Phản Hồi Thành Công (201 Created)
```json
{
  "transaction_id": "98765432-abcd-ef01-2345-6789abcdef01",
  "status": "CONFIRMED",
  "idempotency_key": "uuid-here",
  "processed_at": "2026-10-22T19:40:00Z"
}
```

## POST /api/v1/webhooks/stripe
Tiếp nhận sự kiện thanh toán hoàn tất bất đồng bộ từ nhà cung cấp với kiểm tra chữ ký số HMAC SHA-256.
