# Orchestration runbook

## Ghi file và console UTF-8 trên Windows (tiếng Việt)

Lỗi từng gặp: nhãn tiếng Việt bị thay bằng `?` hoặc thành mojibake (`Ã`, `Ä`) khi ghi file qua PowerShell/console mặc định (code page 1252/437).

- Mở console: `chcp 65001` và `[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)`; `$OutputEncoding = [Text.UTF8Encoding]::new($false)` (dùng cho dữ liệu pipe sang chương trình ngoài).
- Ghi file: dùng `[IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))` (UTF-8 không BOM). Tránh `Set-Content -Encoding utf8` trên Windows PowerShell 5.1 vì thêm BOM; tránh `>`/`Out-File` mặc định.
- Python: `open(path, "w", encoding="utf-8")` và `Path.read_text(encoding="utf-8")`; không dựa vào locale.
- Truyền văn bản có dấu qua dòng lệnh có thể bị hỏng: ghi vào file UTF-8 rồi đọc lại.
- Kiểm tra: `tests/test_review_labels.py::test_labels_are_clean_vietnamese_utf8` (UTF-8 hợp lệ, không có `?`, U+FFFD hoặc mojibake, đủ khoá cho mọi enum/mã lỗi).