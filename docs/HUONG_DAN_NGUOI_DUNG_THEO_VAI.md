# Hướng dẫn sử dụng OrchestrIQ Studio theo vai

Mỗi mục là các việc thường ngày của một vai, làm theo thứ tự. Mọi câu trả lời có nút nguồn: bấm để xem đúng đoạn tài liệu ở cột phải. Hệ thống chạy trên máy chủ của tổ chức; tài liệu không gửi ra ngoài.

## Người dùng cá nhân (sinh viên, nhân viên văn phòng)

1. Đăng ký, đăng nhập. Ở Không gian làm việc, bấm **Tải tài liệu của bạn lên** (PDF, Word, Excel, Markdown, ảnh chụp) hoặc thử một **bộ mẫu theo ngành**.
2. Hỏi bằng câu bình thường: "Đi công tác tỉnh khác 4 ngày được phụ cấp bao nhiêu, ai duyệt?". Hệ thống tự chọn: trả lời thẳng, gọi kỹ năng, hoặc chia việc cho nhiều tác tử.
3. Cột phải: **Câu trả lời này dùng** (các đoạn nguồn), **Phạm vi hỏi** (bỏ chọn tài liệu không muốn dùng), **Quá trình xử lý** (các bước, thời gian, token). Bấm biểu tượng thu gọn để mở rộng khung chat.
4. Dưới câu trả lời: **Lưu vào Kết quả**, **Xuất Word**, **Mở nguồn**, **Hiểu sai? Chọn lại** (hệ thống nhớ cách hiểu bạn chọn cho câu tương tự).
5. Gõ "/" để chọn kỹ năng: Kiểm tra điều kiện, Quy trình từng bước, Ai duyệt, Rà soát hợp đồng, Hiệu lực văn bản, So sánh phiên bản, Tạo câu hỏi trắc nghiệm, Rà soát theo tiêu chí, Bảng dữ liệu theo quy định.
6. **Lịch sử** (góc trên phải): mở lại, đổi tên, ghim, xóa cuộc trò chuyện.

## Giảng viên, cán bộ đào tạo

- **Tạo câu hỏi ôn tập:** gõ "Tạo 10 câu hỏi trắc nghiệm về chương 2" → thẻ câu hỏi có 4 phương án, đáp án, giải thích, nguồn. Kiểm tra lại trước khi dùng.
- **Xét điều kiện một sinh viên:** "Sinh viên ĐTB 3,4, rèn luyện 65 có được học bổng không?" → từng điều kiện Đạt/Không đạt/Chưa rõ kèm Điều khoản.
- **Xét cả lớp:** Kỹ năng → Xét duyệt theo danh sách: tải bảng điểm (Excel hoặc CSV), xác nhận ngưỡng lấy từ quy chế, máy tính từng dòng.
- **Tra cứu quy chế theo Điều:** Kỹ năng → Tra cứu quy chế theo Điều.
- **So sánh quy chế cũ/mới:** trang So sánh phiên bản, chọn cặp gợi ý, lọc Thêm/Sửa/Bỏ, xuất Word/Excel.

## Nhân viên trong tổ chức

- Chọn tổ chức ở ô không gian (góc trên phải). Chỉ thấy tài liệu được phép theo cấp và phòng; tài liệu Mật không hiện và không hỏi ra được.
- Hỏi chính sách: "Làm thêm ngày nghỉ được trả bao nhiêu?", "Ai duyệt đơn nghỉ 4 ngày?".
- **Gửi đơn:** Kết quả & công việc → Đơn từ: nhập đơn, bấm kiểm tra theo quy định, chọn cấp duyệt, gửi. Nếu không có ai duyệt được ở cấp đã chọn, hệ thống báo và khóa nút gửi.
- Theo dõi đơn và thông báo ở tab Đơn từ, Thông báo.

## Trưởng phòng, Ban giám đốc

- **Duyệt đơn:** Kết quả & công việc → Cần xem xét (đơn chờ duyệt) → Đơn từ: duyệt hoặc từ chối kèm ghi chú; xem lịch sử đơn đã xử lý. Trưởng phòng duyệt đơn cấp phòng mình; Ban giám đốc và chủ tổ chức duyệt mọi đơn.
- **Công bố tài liệu:** tải lên trong tổ chức, chọn mức: Toàn tổ chức, Phòng ban, Hạn chế, Mật, Riêng tư.
- **Theo dõi tài liệu mới:** khi tải bản mới thay bản cũ, hệ thống báo và gợi ý So sánh phiên bản; mâu thuẫn giữa tài liệu ở Kiểm tra mâu thuẫn.
- **Nhật ký tài liệu Mật:** trang Tổ chức, xem ai đã xem hoặc hỏi về tài liệu Mật.
- **Tổng quan:** việc đang dở, cảnh báo kho, đơn chờ, tài liệu mới.

## Quản trị hệ thống

- Cấp quyền quản trị (máy chủ): xem `docs/HUONG_DAN_VAN_HANH_MAY_CHU.md`.
- Cổng quản trị (nút chuyển ở thanh bên): người dùng (khóa, đổi vai, đặt lại mật khẩu, thu hồi phiên), nhật ký thao tác, cấu hình AI, tình trạng dịch vụ, phản hồi người dùng.
- Sao lưu, khôi phục, nâng cấp, OCR, đăng nhập tài khoản tổ chức (OIDC): theo hướng dẫn vận hành.

## Nhà nghiên cứu (nhóm C1SE.27)

- Bật Chế độ nhà nghiên cứu trong Cài đặt để hiện nhóm Nghiên cứu: Phòng đánh giá (chạy A, B, C, C-P, C-N, C-O trên bộ câu hỏi), Thực nghiệm (nhật ký lượt chạy), Chấm mù (người chấm theo mã đợt).
- Thực nghiệm A/B/C chạy như cũ; các cải tiến của chế độ sản phẩm (truy xuất lai, học từ người dùng) không áp dụng cho chúng.
