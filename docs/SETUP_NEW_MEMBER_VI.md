# Cài đặt từ máy sạch

1. Cài Git, Docker Desktop, Python 3.12+, Node/npm và Ollama.
2. Giải nén gói, mở PowerShell tại thư mục gói.
3. Chạy `scripts/01_check_prerequisites.ps1`.
4. Đặt `DATABASE_URL` tới PostgreSQL mới; chạy `02_setup_backend.ps1`.
5. Chạy `03_setup_frontend.ps1`.
6. Tạo database mới, chạy `04_restore_postgres.ps1`.
7. Chạy `05_prepare_qdrant.ps1` và `06_check_ollama.ps1`.
8. Chạy `START_CAP1_MIDTERM.ps1`, sau đó `VERIFY_CAP1_MIDTERM.ps1`.
9. Mở `http://127.0.0.1:5176` và đăng ký user QA mới.

Không clone frontend khác và không dùng file `.env` từ máy nguồn.
