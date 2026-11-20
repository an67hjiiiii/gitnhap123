# BÀI GIẢNG CƠ SỞ DỮ LIỆU – CHƯƠNG 2: MÔ HÌNH QUAN HỆ (TÀI LIỆU MẪU)

> Tài liệu mẫu do nhóm C1SE.27 tự soạn để thử kỹ năng tạo câu hỏi ôn tập. Không trích từ giáo trình có bản quyền.

## Mục tiêu bài học
Sau chương này, sinh viên giải thích được quan hệ, khóa chính, khóa ngoại và ba dạng chuẩn đầu tiên.

## 2.1 Quan hệ, bộ và thuộc tính
Một quan hệ là một bảng gồm các hàng (bộ) và các cột (thuộc tính). Mỗi thuộc tính có một miền giá trị. Thứ tự các hàng không mang ý nghĩa.

## 2.2 Khóa
Định nghĩa: siêu khóa là tập thuộc tính xác định duy nhất mỗi bộ. Khóa chính là siêu khóa tối thiểu được chọn để định danh bộ. Khóa ngoại là thuộc tính tham chiếu đến khóa chính của một quan hệ khác.
Ví dụ: trong quan hệ SINHVIEN(MaSV, HoTen, MaLop), MaSV là khóa chính; MaLop là khóa ngoại tham chiếu LOP(MaLop).

## 2.3 Ràng buộc toàn vẹn
Ràng buộc thực thể: khóa chính không được rỗng. Ràng buộc tham chiếu: giá trị khóa ngoại phải tồn tại ở quan hệ được tham chiếu hoặc rỗng.

## 2.4 Chuẩn hóa
- Dạng chuẩn 1 (1NF): mọi thuộc tính chỉ chứa giá trị nguyên tố, không có nhóm lặp.
- Dạng chuẩn 2 (2NF): đạt 1NF và mọi thuộc tính không khóa phụ thuộc đầy đủ vào khóa chính.
- Dạng chuẩn 3 (3NF): đạt 2NF và không có thuộc tính không khóa phụ thuộc bắc cầu vào khóa chính.

## Câu hỏi ôn tập
1. Phân biệt siêu khóa và khóa chính.
2. Vì sao khóa chính không được rỗng?
3. Cho một ví dụ vi phạm dạng chuẩn 3.
