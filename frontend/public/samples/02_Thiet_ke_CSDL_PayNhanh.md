# THIẾT KẾ CƠ SỞ DỮ LIỆU – CỔNG THANH TOÁN PAYNHANH

Mã tài liệu: PN-DB-02 · Phiên bản 1.1 · Ngày: 05/11/2026
Hệ quản trị: PostgreSQL 16 · Căn cứ: Đặc tả yêu cầu PN-SRS-01

## 1. Nguyên tắc thiết kế
1. Tiền luôn lưu bằng kiểu BIGINT theo đơn vị đồng (VND), không dùng số thực để tránh sai số làm tròn.
2. Mọi bảng nghiệp vụ có cột created_at và updated_at kiểu TIMESTAMPTZ, lưu theo giờ UTC.
3. Khóa chính dùng chuỗi có tiền tố dễ đọc, ví dụ pay_, txn_, ref_, sinh ngẫu nhiên 16 ký tự, để không lộ số lượng đơn.
4. Không xóa cứng dữ liệu giao dịch. Bản ghi sai được đánh dấu, không DELETE.
5. Lịch sử trạng thái lưu ở bảng riêng theo kiểu chỉ thêm (append-only).
6. Dữ liệu nhạy cảm (số tài khoản ngân hàng merchant, khóa bí mật webhook) được mã hóa ở tầng ứng dụng bằng AES-256-GCM trước khi ghi.

## 2. Danh sách bảng chính
| Bảng | Mục đích |
|---|---|
| merchants | Thông tin cửa hàng, trạng thái duyệt |
| merchant_users | Tài khoản người dùng thuộc merchant và vai trò |
| api_keys | Khóa API (chỉ lưu băm) |
| payments | Đơn thanh toán |
| payment_status_history | Lịch sử chuyển trạng thái đơn |
| transactions | Từng lần giao dịch với ngân hàng hoặc ví |
| idempotency_records | Bản ghi chống tạo đơn trùng |
| refunds | Yêu cầu hoàn tiền |
| webhook_endpoints | Cấu hình URL nhận webhook |
| webhook_deliveries | Từng lần gửi webhook và kết quả |
| reconciliation_reports | Kết quả đối soát hằng ngày |
| audit_logs | Nhật ký kiểm toán |

## 3. Chi tiết các bảng quan trọng

### 3.1 Bảng payments
| Cột | Kiểu | Ràng buộc | Ghi chú |
|---|---|---|---|
| payment_id | VARCHAR(24) | PK | Ví dụ pay_8f2k... |
| merchant_id | VARCHAR(24) | FK → merchants, NOT NULL | |
| merchant_order_id | VARCHAR(64) | NOT NULL | Mã đơn hàng phía merchant |
| amount | BIGINT | CHECK (amount BETWEEN 1000 AND 500000000) | Đơn vị đồng |
| refunded_amount | BIGINT | DEFAULT 0, CHECK (refunded_amount <= amount) | |
| currency | CHAR(3) | DEFAULT 'VND' | |
| status | VARCHAR(24) | NOT NULL | PENDING, PROCESSING, SUCCEEDED, FAILED, EXPIRED, PARTIALLY_REFUNDED, REFUNDED |
| allowed_methods | TEXT[] | | napas, ewallet, vietqr |
| expires_at | TIMESTAMPTZ | NOT NULL | created_at + 15 phút |
| version | INTEGER | DEFAULT 0 | Khóa lạc quan |

Ràng buộc duy nhất: UNIQUE (merchant_id, merchant_order_id) để một mã đơn hàng của merchant chỉ ứng với một đơn thanh toán.
Chỉ mục: (merchant_id, created_at DESC) cho bảng điều khiển; (status, expires_at) cho tác vụ đánh dấu đơn hết hạn.

### 3.2 Bảng idempotency_records
| Cột | Kiểu | Ràng buộc |
|---|---|---|
| merchant_id | VARCHAR(24) | PK phần 1 |
| idempotency_key | VARCHAR(128) | PK phần 2 |
| request_hash | CHAR(64) | NOT NULL – SHA-256 của thân yêu cầu đã chuẩn hóa |
| payment_id | VARCHAR(24) | FK → payments |
| response_body | JSONB | Phản hồi đã trả lần đầu |
| expires_at | TIMESTAMPTZ | created_at + 24 giờ |

Cách dùng: khi nhận yêu cầu tạo đơn, ứng dụng mở giao dịch và chạy INSERT ... ON CONFLICT (merchant_id, idempotency_key) DO NOTHING. Nếu chèn thành công thì tạo đơn mới. Nếu bị trùng, đọc bản ghi cũ: request_hash giống thì trả lại response_body; khác thì trả lỗi 409 IDEMPOTENCY_CONFLICT. Khóa chính kép đảm bảo hai yêu cầu đến cùng lúc cũng chỉ một yêu cầu chèn được, kể cả khi chạy trên nhiều máy chủ ứng dụng.

### 3.3 Bảng transactions
| Cột | Kiểu | Ghi chú |
|---|---|---|
| transaction_id | VARCHAR(24) PK | |
| payment_id | VARCHAR(24) FK | |
| method | VARCHAR(16) | napas, ewallet, vietqr |
| provider_reference | VARCHAR(64) | Mã tham chiếu từ ngân hàng, UNIQUE |
| amount | BIGINT | |
| status | VARCHAR(16) | INITIATED, SUCCEEDED, FAILED, REVERSED |
| card_bin | CHAR(6) | 6 số đầu thẻ, có thể NULL |
| card_last4 | CHAR(4) | 4 số cuối thẻ |

Chỉ mục duy nhất có điều kiện: CREATE UNIQUE INDEX one_success_per_payment ON transactions(payment_id) WHERE status = 'SUCCEEDED'. Chỉ mục này bảo đảm ở mức cơ sở dữ liệu rằng mỗi đơn chỉ có một giao dịch thành công (yêu cầu FR-04). Nếu ngân hàng báo thành công lần thứ hai, lệnh cập nhật bị từ chối, ứng dụng ghi giao dịch đó là REVERSED và tạo yêu cầu hoàn trả tự động.

Không bao giờ lưu số thẻ đầy đủ, ngày hết hạn hay mã CVV.

### 3.4 Bảng payment_status_history
| Cột | Kiểu |
|---|---|
| id | BIGSERIAL PK |
| payment_id | VARCHAR(24) FK |
| from_status | VARCHAR(24) |
| to_status | VARCHAR(24) |
| reason | TEXT |
| actor | VARCHAR(64) – system, operator:<id>, merchant:<id> |
| created_at | TIMESTAMPTZ |

Bảng chỉ cho phép INSERT. Quyền UPDATE và DELETE bị thu hồi khỏi tài khoản ứng dụng.

### 3.5 Bảng refunds
| Cột | Kiểu | Ghi chú |
|---|---|---|
| refund_id | VARCHAR(24) PK | |
| payment_id | VARCHAR(24) FK | |
| amount | BIGINT | > 0 |
| status | VARCHAR(16) | REQUESTED, APPROVED, PROCESSING, SUCCEEDED, FAILED, REJECTED |
| requires_approval | BOOLEAN | TRUE nếu amount >= 10.000.000 |
| approved_by | VARCHAR(24) | Người duyệt thuộc vai trò Finance |
| idempotency_key | VARCHAR(128) | UNIQUE theo merchant |

Khi tạo hoàn tiền, ứng dụng khóa dòng đơn bằng SELECT ... FOR UPDATE, kiểm tra refunded_amount + amount <= payments.amount, cập nhật refunded_amount trong cùng giao dịch. Cách này ngăn hai yêu cầu hoàn tiền đồng thời làm tổng tiền hoàn vượt số đã thanh toán.

### 3.6 Bảng webhook_deliveries
| Cột | Kiểu | Ghi chú |
|---|---|---|
| delivery_id | VARCHAR(24) PK | |
| event_id | VARCHAR(24) | Mã sự kiện duy nhất gửi cho merchant |
| endpoint_id | VARCHAR(24) FK | |
| attempt | SMALLINT | 1 đến 9 |
| response_code | SMALLINT | |
| next_retry_at | TIMESTAMPTZ | NULL nếu đã thành công hoặc hết lượt |
| payload | JSONB | |

Chỉ mục (next_retry_at) WHERE next_retry_at IS NOT NULL cho tác vụ gửi lại.

### 3.7 Bảng audit_logs
Ghi các sự kiện: đăng nhập, tạo và thu hồi khóa API, đổi vai trò, duyệt hoàn tiền, xuất dữ liệu, thay đổi cấu hình. Mỗi dòng có actor, hành động, đối tượng, địa chỉ IP, user agent, thời điểm và băm của dòng trước đó (chuỗi băm) để phát hiện sửa đổi. Bảng được phân vùng theo tháng và lưu 5 năm.

## 4. Quan hệ giữa các bảng
- Một merchant có nhiều merchant_users, api_keys, payments, webhook_endpoints.
- Một payment có nhiều transactions, nhiều refunds, nhiều dòng payment_status_history.
- Một payment có đúng một idempotency_record tạo ra nó.
- Một webhook_endpoint có nhiều webhook_deliveries.

## 5. Giao dịch và mức cô lập
- Mặc định READ COMMITTED.
- Tạo đơn, ghi nhận thanh toán và hoàn tiền dùng giao dịch ngắn, khóa dòng cụ thể bằng SELECT ... FOR UPDATE thay vì nâng mức SERIALIZABLE toàn cục.
- Cập nhật trạng thái đơn dùng khóa lạc quan: UPDATE payments SET status = :new, version = version + 1 WHERE payment_id = :id AND version = :old. Nếu không có dòng nào được cập nhật thì đọc lại và thử lại tối đa 3 lần.

## 6. Sao lưu và khôi phục
- Bật WAL archiving liên tục lên kho lưu trữ riêng, đáp ứng RPO 5 phút.
- Sao lưu toàn bộ hằng ngày lúc 02:00, giữ 35 ngày.
- Mỗi quý diễn tập khôi phục trên môi trường tách biệt và ghi lại thời gian khôi phục thực tế.
- Có một bản sao đọc (read replica) phục vụ báo cáo, không phục vụ ghi.

## 7. Phân quyền cơ sở dữ liệu
| Tài khoản | Quyền |
|---|---|
| app_rw | SELECT, INSERT, UPDATE trên bảng nghiệp vụ; chỉ INSERT trên payment_status_history và audit_logs |
| report_ro | SELECT trên bản sao đọc, không thấy cột mã hóa |
| migration | DDL, chỉ dùng trong quy trình triển khai |
Không ai dùng tài khoản postgres trong vận hành hằng ngày.

## 8. Quản lý thay đổi lược đồ
Mọi thay đổi lược đồ qua Alembic, có kịch bản nâng và hạ cấp. Đổi tên hoặc bỏ cột theo hai bước "mở rộng rồi thu gọn": thêm cột mới, ghi song song, chuyển đọc, rồi mới bỏ cột cũ ở lần phát hành sau.
