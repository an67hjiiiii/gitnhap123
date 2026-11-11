# CAP1_AI Midterm Portable Handoff

Gói này chứa Product UI React/Vite đã khóa, backend FastAPI hiện tại, demo
corpus song ngữ và dữ liệu dẫn xuất cần cho demo local. PostgreSQL là nguồn dữ
liệu có thẩm quyền; Qdrant chỉ là index dẫn xuất. Dump PostgreSQL đã được
ẩn danh: chỉ còn một user demo tổng hợp, không có session/conversation/run
private lịch sử.

Không commit mật khẩu, token, cookie hoặc file `.env` thật. Đặt
`DATABASE_URL` trong phiên PowerShell trước khi chạy script.
