# ĐẶC TẢ YÊU CẦU PHẦN MỀM – CỔNG THANH TOÁN PAYNHANH

Mã tài liệu: PN-SRS-01 · Phiên bản 1.3 · Ngày phát hành: 02/11/2026
Đơn vị soạn thảo: Nhóm Sản phẩm và Kỹ thuật, Công ty TNHH Công nghệ PayNhanh (doanh nghiệp giả định dùng cho báo cáo)
Người phê duyệt: Giám đốc Kỹ thuật

## 1. Giới thiệu

### 1.1 Mục đích tài liệu
Tài liệu này mô tả đầy đủ các yêu cầu chức năng và phi chức năng của Cổng thanh toán PayNhanh phiên bản 1.0. Tài liệu là căn cứ để đội phát triển thiết kế cơ sở dữ liệu, thiết kế API, xây dựng chính sách bảo mật, lập kế hoạch kiểm thử và nghiệm thu với đối tác.

### 1.2 Phạm vi sản phẩm
PayNhanh là cổng thanh toán trung gian cho các cửa hàng trực tuyến vừa và nhỏ tại Việt Nam. Cổng cho phép cửa hàng (gọi là "merchant") nhận tiền từ người mua qua ba phương thức: thẻ nội địa Napas, ví điện tử và chuyển khoản ngân hàng bằng mã QR VietQR. Cổng không giữ tiền của khách hàng quá thời gian đối soát cuối ngày; tiền được chuyển về tài khoản merchant theo chu kỳ T+1.

Ngoài phạm vi phiên bản 1.0: thẻ quốc tế Visa/Mastercard, trả góp, thanh toán định kỳ (subscription) và ứng dụng di động riêng cho merchant.

### 1.3 Thuật ngữ
- Merchant: cửa hàng hoặc doanh nghiệp tích hợp PayNhanh để nhận tiền.
- Đơn thanh toán (payment): một yêu cầu thu tiền gắn với một đơn hàng của merchant.
- Giao dịch (transaction): một lần thực hiện chuyển tiền với ngân hàng hoặc ví; một đơn thanh toán có thể có nhiều giao dịch nếu lần đầu thất bại.
- Idempotency key: chuỗi duy nhất do merchant gửi kèm mỗi yêu cầu tạo đơn, giúp hệ thống nhận ra yêu cầu bị gửi lặp và không tạo đơn thứ hai.
- Webhook: thông báo tự động PayNhanh gửi đến máy chủ merchant khi trạng thái đơn thay đổi.
- Đối soát: so khớp số liệu giao dịch của PayNhanh với sao kê của ngân hàng đối tác vào cuối mỗi ngày.
- Hoàn tiền (refund): trả lại toàn bộ hoặc một phần số tiền của một đơn đã thanh toán thành công.

### 1.4 Đối tượng sử dụng
| Vai trò | Mô tả | Quyền chính |
|---|---|---|
| Người mua | Khách hàng của merchant | Trả tiền, xem trạng thái thanh toán |
| Merchant Owner | Chủ cửa hàng | Toàn quyền tài khoản merchant, tạo khóa API, xem doanh thu, yêu cầu hoàn tiền |
| Merchant Staff | Nhân viên cửa hàng | Xem đơn, tra cứu giao dịch, không được hoàn tiền |
| Operator | Nhân viên vận hành PayNhanh | Hỗ trợ merchant, xem nhật ký, xử lý khiếu nại |
| Finance | Kế toán PayNhanh | Đối soát, duyệt hoàn tiền lớn, xuất báo cáo |
| Admin | Quản trị hệ thống | Quản lý tài khoản nội bộ, cấu hình, phân quyền |

## 2. Bối cảnh và vấn đề cần giải quyết
Khảo sát 40 cửa hàng trực tuyến do nhóm sản phẩm thực hiện tháng 8/2026 ghi nhận ba vấn đề lặp lại nhiều nhất:
1. Khách bị trừ tiền hai lần khi mạng chập chờn và bấm nút "Thanh toán" nhiều lần.
2. Cửa hàng không biết đơn đã thanh toán hay chưa vì thông báo từ cổng cũ đến chậm hoặc mất.
3. Hoàn tiền mất từ 5 đến 10 ngày và phải gọi điện nhiều lần.
Ba vấn đề này là mục tiêu ưu tiên của phiên bản 1.0.

## 3. Yêu cầu chức năng

### FR-01 Đăng ký và xác minh merchant
- Merchant đăng ký bằng email doanh nghiệp, số điện thoại và mã số thuế.
- Hệ thống gửi mã xác minh email có hiệu lực 15 phút.
- Merchant tải lên giấy phép kinh doanh; Operator duyệt trong vòng 2 ngày làm việc.
- Chỉ merchant đã duyệt mới được tạo khóa API môi trường thật (live). Môi trường thử (sandbox) mở ngay sau khi xác minh email.

### FR-02 Quản lý khóa API
- Mỗi merchant có tối đa 5 khóa API đang hoạt động cho mỗi môi trường.
- Khóa bí mật chỉ hiển thị một lần khi tạo; hệ thống chỉ lưu giá trị băm.
- Merchant Owner có thể thu hồi khóa; khóa bị thu hồi mất hiệu lực trong vòng 60 giây.
- Mỗi lần tạo hoặc thu hồi khóa phải được ghi vào nhật ký kiểm toán.

### FR-03 Tạo đơn thanh toán
- Merchant gọi API tạo đơn với: mã đơn hàng của merchant, số tiền (VND, số nguyên, từ 1.000 đến 500.000.000), mô tả, URL quay lại, phương thức cho phép và idempotency key.
- Idempotency key là bắt buộc. Nếu cùng merchant gửi lại cùng key trong 24 giờ với cùng nội dung, hệ thống trả lại đúng đơn đã tạo, không tạo đơn mới. Nếu cùng key nhưng nội dung khác, hệ thống trả lỗi 409 IDEMPOTENCY_CONFLICT.
- Đơn mới có trạng thái PENDING và hết hạn sau 15 phút nếu người mua không thanh toán.

### FR-04 Thanh toán
- Người mua chọn phương thức trên trang thanh toán của PayNhanh.
- Với VietQR: hệ thống sinh mã QR chứa số tiền và nội dung chuyển khoản duy nhất; khi ngân hàng báo tiền về, đơn chuyển sang SUCCEEDED.
- Với thẻ Napas: chuyển hướng sang trang xác thực OTP của ngân hàng phát hành.
- Nút "Thanh toán" bị khóa ngay sau lần bấm đầu tiên; giao diện hiển thị "Đang xử lý" cho đến khi có kết quả.
- Một đơn chỉ có thể có tối đa một giao dịch thành công. Mọi giao dịch thành công thứ hai cho cùng đơn phải bị tự động hoàn trả và tạo cảnh báo cho Operator.

### FR-05 Vòng đời trạng thái đơn
Các trạng thái hợp lệ: PENDING → PROCESSING → SUCCEEDED hoặc FAILED hoặc EXPIRED. Từ SUCCEEDED có thể chuyển sang PARTIALLY_REFUNDED hoặc REFUNDED. Không được chuyển ngược từ SUCCEEDED về PENDING. Mọi lần chuyển trạng thái được lưu thành một bản ghi lịch sử riêng, không ghi đè.

### FR-06 Webhook
- Khi trạng thái đơn thay đổi, PayNhanh gửi webhook POST đến URL merchant đã cấu hình.
- Mỗi webhook có header X-PayNhanh-Signature là chữ ký HMAC-SHA256 của thân thông báo cộng dấu thời gian, dùng khóa bí mật webhook riêng của merchant.
- Merchant phải trả mã 2xx trong 10 giây. Nếu không, hệ thống gửi lại tối đa 8 lần với khoảng cách tăng dần: 1 phút, 5 phút, 15 phút, 1 giờ, 3 giờ, 6 giờ, 12 giờ, 24 giờ.
- Mỗi webhook có mã sự kiện duy nhất để merchant tự loại bỏ thông báo trùng.
- Merchant có thể xem lịch sử gửi webhook và bấm "Gửi lại" thủ công.

### FR-07 Hoàn tiền
- Merchant Owner tạo yêu cầu hoàn tiền toàn bộ hoặc một phần trong vòng 180 ngày kể từ ngày thanh toán.
- Tổng số tiền hoàn không được vượt số tiền đã thanh toán.
- Hoàn tiền dưới 10.000.000 VND được xử lý tự động. Từ 10.000.000 VND trở lên cần Finance duyệt.
- Mục tiêu: tiền về tài khoản người mua trong tối đa 3 ngày làm việc đối với VietQR và 7 ngày làm việc đối với thẻ.

### FR-08 Đối soát cuối ngày
- Lúc 01:00 hằng ngày, hệ thống tải sao kê từ ngân hàng đối tác và so khớp với giao dịch nội bộ theo mã tham chiếu.
- Các chênh lệch được phân loại: thiếu bên ngân hàng, thiếu bên PayNhanh, lệch số tiền.
- Báo cáo đối soát gửi cho Finance trước 08:00. Chênh lệch chưa xử lý quá 3 ngày được nâng mức cảnh báo.

### FR-09 Bảng điều khiển merchant
- Doanh thu theo ngày, tuần, tháng; tỷ lệ thanh toán thành công; danh sách đơn có bộ lọc theo trạng thái, phương thức, khoảng thời gian.
- Xuất danh sách đơn ra CSV tối đa 100.000 dòng mỗi lần.

### FR-10 Phân quyền
Phân quyền theo vai trò (RBAC) như bảng ở mục 1.4. Mọi API nội bộ phải kiểm tra quyền ở phía máy chủ; không dựa vào việc ẩn nút trên giao diện. Merchant chỉ được xem dữ liệu của chính mình.

## 4. Yêu cầu phi chức năng
| Mã | Yêu cầu | Chỉ tiêu mục tiêu |
|---|---|---|
| NFR-01 | Hiệu năng API tạo đơn | 95% yêu cầu phản hồi dưới 300 ms ở tải 200 yêu cầu/giây |
| NFR-02 | Sẵn sàng | 99,9% mỗi tháng, không tính bảo trì có báo trước |
| NFR-03 | Bảo mật dữ liệu thẻ | Không lưu số thẻ đầy đủ; chỉ lưu 6 số đầu và 4 số cuối |
| NFR-04 | Mã hóa | TLS 1.2 trở lên khi truyền; mã hóa AES-256 khi lưu dữ liệu nhạy cảm |
| NFR-05 | Nhật ký | Lưu nhật ký kiểm toán tối thiểu 5 năm, không cho phép sửa |
| NFR-06 | Khôi phục | RPO 5 phút, RTO 1 giờ |
| NFR-07 | Tuân thủ | Hướng tới PCI DSS v4.0 và quy định của Ngân hàng Nhà nước về trung gian thanh toán |

Các chỉ tiêu trên là mục tiêu thiết kế, chưa phải kết quả đo.

## 5. Tình huống sử dụng tiêu biểu

### UC-01 Người mua bấm thanh toán hai lần
Người mua bấm "Thanh toán", mạng chậm, bấm lại. Trình duyệt của merchant gửi hai yêu cầu tạo đơn với cùng idempotency key. PayNhanh nhận yêu cầu thứ hai, thấy key đã tồn tại với cùng nội dung, trả lại đơn cũ. Người mua chỉ bị trừ tiền một lần.

### UC-02 Máy chủ merchant tạm ngừng
Máy chủ merchant bảo trì 2 giờ. Webhook SUCCEEDED gửi thất bại, hệ thống tự gửi lại theo lịch. Sau khi máy chủ hoạt động lại, merchant nhận webhook ở lần gửi lại thứ 5 và cập nhật đơn hàng.

### UC-03 Hoàn tiền một phần
Khách trả một sản phẩm trong đơn 1.200.000 VND. Merchant Owner hoàn 450.000 VND. Đơn chuyển sang PARTIALLY_REFUNDED; số tiền còn có thể hoàn là 750.000 VND.

## 6. Tiêu chí nghiệm thu
- 100% ca kiểm thử chức năng FR-03 đến FR-07 đạt trên môi trường sandbox.
- Kiểm thử gửi lặp 1.000 yêu cầu cùng idempotency key chỉ tạo đúng một đơn.
- Kiểm thử bảo mật không còn lỗ hổng mức Cao hoặc Nghiêm trọng.
- Tài liệu API và hướng dẫn tích hợp được ba merchant thử nghiệm xác nhận dễ hiểu.

## 7. Lịch phát hành dự kiến
| Mốc | Thời gian | Nội dung |
|---|---|---|
| M1 | 30/11/2026 | Hoàn thành tạo đơn, VietQR, webhook trên sandbox |
| M2 | 31/12/2026 | Thẻ Napas, hoàn tiền, đối soát |
| M3 | 31/01/2027 | Kiểm thử bảo mật, thử nghiệm với 3 merchant |
| M4 | 28/02/2027 | Phát hành chính thức |
