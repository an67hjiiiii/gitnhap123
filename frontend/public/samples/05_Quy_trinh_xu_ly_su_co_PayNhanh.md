# QUY TRÌNH VẬN HÀNH VÀ XỬ LÝ SỰ CỐ – PAYNHANH

Mã tài liệu: PN-OPS-05 · Phiên bản 1.4 · Ngày: 08/11/2026
Áp dụng cho: nhóm Vận hành (Operator), kỹ sư trực (on-call), Trưởng nhóm Kỹ thuật

## 1. Mục đích
Thống nhất cách phát hiện, phân loại, xử lý và rút kinh nghiệm khi hệ thống thanh toán gặp sự cố, để giảm thời gian gián đoạn và tránh thiệt hại cho merchant và người mua.

## 2. Ca trực
- Trực 24/7 theo tuần, mỗi tuần một kỹ sư chính và một kỹ sư dự phòng.
- Kỹ sư chính phải xác nhận cảnh báo trong 5 phút. Quá 5 phút, cảnh báo tự chuyển cho kỹ sư dự phòng; quá 15 phút chuyển cho Trưởng nhóm Kỹ thuật.
- Bàn giao ca vào 09:00 thứ Hai, kèm danh sách sự cố đang mở.

## 3. Phân loại mức độ sự cố
| Mức | Định nghĩa | Ví dụ | Mục tiêu khắc phục |
|---|---|---|---|
| SEV-1 | Không thể nhận thanh toán, hoặc có rủi ro mất tiền | API tạo đơn lỗi trên 50%; trừ tiền hai lần hàng loạt | Khôi phục trong 1 giờ |
| SEV-2 | Một phần chức năng chính hỏng | Một ngân hàng đối tác không phản hồi; webhook chậm trên 30 phút | 4 giờ |
| SEV-3 | Ảnh hưởng nhỏ, có cách tạm thời | Xuất CSV lỗi; bảng điều khiển tải chậm | 2 ngày làm việc |
| SEV-4 | Không ảnh hưởng khách hàng | Cảnh báo dung lượng ổ đĩa 70% | Theo kế hoạch |

## 4. Các chỉ số được giám sát
| Chỉ số | Ngưỡng cảnh báo |
|---|---|
| Tỷ lệ lỗi 5xx của API tạo đơn | > 2% trong 5 phút |
| Độ trễ p95 API tạo đơn | > 800 ms trong 10 phút |
| Tỷ lệ thanh toán thành công theo ngân hàng | Giảm hơn 20% so với cùng giờ tuần trước |
| Số webhook đang chờ gửi lại | > 5.000 |
| Độ trễ sao chép của bản sao đọc | > 60 giây |
| Kết nối cơ sở dữ liệu đang dùng | > 80% giới hạn |
| Giao dịch thành công thứ hai cho cùng đơn | Bất kỳ trường hợp nào |

## 5. Quy trình chung khi có sự cố
1. **Xác nhận**: kỹ sư trực xác nhận cảnh báo, mở kênh sự cố riêng, đặt tên theo mẫu "SC-ngày-tóm tắt".
2. **Phân loại**: xác định mức SEV theo bảng mục 3. SEV-1 và SEV-2 phải chỉ định một Người chỉ huy sự cố (Incident Commander) và một người phụ trách liên lạc.
3. **Thông báo**: SEV-1 cập nhật trang trạng thái công khai trong 15 phút; gửi email cho merchant bị ảnh hưởng.
4. **Giảm thiểu trước, tìm nguyên nhân sau**: ưu tiên khôi phục dịch vụ (quay lại phiên bản trước, tắt tính năng lỗi, chuyển ngân hàng dự phòng) trước khi điều tra sâu.
5. **Khắc phục**: sửa lỗi, kiểm tra lại các chỉ số đã về ngưỡng bình thường ít nhất 30 phút.
6. **Đóng sự cố**: cập nhật trang trạng thái, gửi thông báo hoàn tất.
7. **Rút kinh nghiệm**: viết báo cáo sau sự cố trong 5 ngày làm việc với SEV-1 và SEV-2.

## 6. Kịch bản xử lý cụ thể

### 6.1 Khách báo bị trừ tiền hai lần
1. Tra cứu đơn theo merchant_order_id; kiểm tra bảng transactions có bao nhiêu giao dịch SUCCEEDED.
2. Nếu có hai đơn khác nhau cho cùng một đơn hàng: kiểm tra merchant có gửi cùng Idempotency-Key không. Nếu merchant sinh key mới mỗi lần thử lại, đây là lỗi tích hợp phía merchant; hướng dẫn merchant theo PN-API-03 mục 5 và hoàn tiền đơn thừa.
3. Nếu cùng một đơn có hai giao dịch thành công: chỉ mục one_success_per_payment lẽ ra phải chặn. Nâng lên SEV-1, kiểm tra giao dịch thứ hai đã được đánh dấu REVERSED và hoàn trả tự động chưa.
4. Phản hồi khách qua merchant trong 4 giờ làm việc, nêu rõ thời gian tiền về.

### 6.2 Webhook không đến được merchant
1. Xem lịch sử gửi trong webhook_deliveries: mã phản hồi, số lần thử, lần thử kế tiếp.
2. Mã 401 hoặc 403 từ merchant thường do merchant xác minh chữ ký sai, ví dụ đã phân tích JSON trước khi tính HMAC. Gửi hướng dẫn kiểm tra chữ ký.
3. Hết thời gian chờ: merchant xử lý quá 10 giây; khuyên merchant trả 200 trước rồi xử lý ở hàng đợi.
4. Sau khi merchant sửa, bấm "Gửi lại" hoặc gọi API resend.
5. Nếu hàng đợi gửi lại vượt 5.000 thông báo trên toàn hệ thống: kiểm tra dịch vụ gửi webhook, tăng số tiến trình gửi, nâng SEV-2.

### 6.3 Ngân hàng đối tác không phản hồi
1. Xác nhận qua chỉ số tỷ lệ thành công theo ngân hàng và trang trạng thái của ngân hàng.
2. Bật cờ cấu hình ẩn phương thức của ngân hàng đó trên trang thanh toán; giữ VietQR qua ngân hàng dự phòng.
3. Giao dịch đang ở trạng thái PROCESSING quá 15 phút: không tự đánh dấu thất bại; đợi kết quả đối soát để tránh trường hợp tiền đã trừ nhưng đơn bị hủy.
4. Liên hệ đầu mối kỹ thuật của ngân hàng theo danh bạ khẩn cấp.

### 6.4 Nghi ngờ lộ khóa API của merchant
1. Thu hồi khóa ngay; khóa hết hiệu lực trong 60 giây.
2. Liên hệ Merchant Owner qua số điện thoại đã xác minh, không qua email trong yêu cầu.
3. Rà soát nhật ký các yêu cầu gọi bằng khóa đó trong 30 ngày: hoàn tiền bất thường, tra cứu hàng loạt.
4. Coi là sự cố bảo mật theo PN-SEC-04 mục 8.

### 6.5 Cơ sở dữ liệu quá tải
1. Kiểm tra truy vấn chạy lâu bằng pg_stat_activity; hủy truy vấn báo cáo chạy nhầm trên máy chủ chính.
2. Chuyển truy vấn báo cáo sang bản sao đọc.
3. Nếu số kết nối gần giới hạn: kiểm tra bộ gộp kết nối, tìm dịch vụ bị rò rỉ kết nối.
4. Không khởi động lại máy chủ cơ sở dữ liệu chính khi chưa có sự đồng ý của Trưởng nhóm Kỹ thuật.

## 7. Triển khai và quay lại phiên bản cũ
- Triển khai trong khung 10:00–16:00 từ thứ Hai đến thứ Năm; không triển khai trước ngày lễ.
- Triển khai dần: 5% lưu lượng trong 15 phút, sau đó 50%, rồi 100%, theo dõi tỷ lệ lỗi ở mỗi bước.
- Mọi bản phát hành phải quay lại được trong 10 phút. Thay đổi cơ sở dữ liệu theo kiểu mở rộng rồi thu gọn để quay lại không mất dữ liệu.

## 8. Mẫu báo cáo sau sự cố
1. Tóm tắt: chuyện gì xảy ra, ảnh hưởng bao nhiêu merchant, bao nhiêu đơn, kéo dài bao lâu.
2. Dòng thời gian theo phút.
3. Nguyên nhân gốc, dùng phương pháp "5 lần tại sao".
4. Điều gì làm tốt, điều gì cần cải thiện.
5. Hành động khắc phục, có người phụ trách và hạn chót.
Báo cáo không quy lỗi cho cá nhân; tập trung vào quy trình và hệ thống.

## 9. Diễn tập
Mỗi quý diễn tập ít nhất một kịch bản SEV-1 trên môi trường thử: ngân hàng ngừng phản hồi, mất một vùng máy chủ, hoặc khôi phục cơ sở dữ liệu từ bản sao lưu.
