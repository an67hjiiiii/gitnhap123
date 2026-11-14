# Known limitations

- Gói không chứa Ollama model; `06_check_ollama.ps1` kiểm tra hoặc pull
  `qwen3:4b` từ Ollama local.
- Qdrant là embedded/local derived index. PostgreSQL vẫn là authoritative.
- Demo corpus là fixture không chuẩn tắc, dùng cho Midterm demo.
- Không bao gồm OCR, DOCX/PPTX, image-only PDF, cloud provider hoặc Sprint 4.

## 2026-11-14 — Phạm vi đã kiểm tra

- Router có quyết định route trong `review/service.py`, nhưng chưa chọn nhánh
  LLM thật cho Review; mức độ tích hợp và đánh giá của Router: chưa xác minh.
- Project Memory chỉ lưu trong bộ nhớ và endpoint gợi ý chỉ đọc; chưa được
  nối vào engine. Chưa đánh giá tác động; không diễn giải đây là kết quả âm.
- Rate limit được giữ trong bộ nhớ tiến trình, nên chỉ dùng chung giữa các
  request của một tiến trình.
- Upload multipart không từ chối sớm theo `Content-Length`; kích thước file
  được kiểm tra khi đọc nội dung.
- PDF text extraction không giới hạn số trang.
- `slot_check` đã xử lý số viết bằng chữ (0-100, en/vi), dấu chấm hàng nghìn, tháng-năm và GB nhị phân; còn yếu: tên riêng nhiều từ tiếng Việt ("Quản trị viên" chỉ giữ "quản"), ràng buộc chủ thể-giá trị và tên một từ đầu câu (xfail trong `test_slot_check.py`).
- Run bị cắt bởi `MAX_RUN_TOKENS` hiện được báo COMPLETE nếu các task đã chạy đều COMPLETE (pipeline.py, xem `test_char_p1_p2.py`).
- Condition C cần `IMPLEMENTATION_PROFILE=dev`; mặc định `m0` chỉ cho A.
- Số đo thực nghiệm trên tập tự dựng chỉ để tham khảo.
