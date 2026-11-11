# Hướng dẫn lấy code, cài và chạy (bản tích hợp C1SE.27 vào CAP1)

Code nằm ở nhánh `tich-hop/studio-c1se27` của repo `an67hjiiiii/gitnhap123`. Nhánh `main` không bị đổi.

## 1. Cần cài trước (một lần)

| Phần mềm | Ghi chú |
|---|---|
| Git | https://git-scm.com |
| Python 3.12 | Tick "Add python.exe to PATH" khi cài |
| Node.js 20 LTS | Có sẵn `npm` |
| Docker Desktop | Chạy PostgreSQL. Mở Docker Desktop trước khi chạy dự án |
| Ollama | https://ollama.com/download (mô hình tự tải ở bước cài đặt) |
| VS Code | Để chạy bằng Ctrl+Shift+B |

Máy nên có ít nhất 16 GB RAM; mô hình qwen3:4b khoảng 2,5 GB, nomic-embed-text khoảng 0,3 GB.

## 2. Lấy code

```powershell
git clone https://github.com/an67hjiiiii/gitnhap123.git
cd gitnhap123
git checkout tich-hop/studio-c1se27
```

Nếu đã clone từ trước:

```powershell
git fetch origin
git checkout tich-hop/studio-c1se27
git pull
```

## 3. Cài đặt lần đầu

Mở thư mục `gitnhap123` bằng VS Code, mở Docker Desktop, rồi chọn **Terminal → Run Task… → Cài đặt lần đầu**.

Task này (file `scripts/dev/setup.ps1`) làm lần lượt: tạo môi trường Python và cài thư viện backend, cài thư viện frontend, bật PostgreSQL trong Docker, tạo bảng dữ liệu (Alembic), tải mô hình `qwen3:4b` và `nomic-embed-text`. Lần đầu mất vài phút đến vài chục phút tùy mạng.

Không dùng VS Code thì chạy trong PowerShell ở thư mục gốc:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/setup.ps1
```

## 4. Chạy dự án: Ctrl + Shift + B

Trong VS Code nhấn **Ctrl + Shift + B** (task mặc định "Chạy toàn bộ dự án"). Ba terminal mở ra:

| Terminal | Làm gì | Địa chỉ |
|---|---|---|
| Ollama | Bật Ollama nếu chưa chạy, tải mô hình nếu thiếu | 127.0.0.1:11434 |
| Backend | Bật PostgreSQL (Docker), cập nhật bảng, chạy FastAPI | 127.0.0.1:8000 |
| Frontend | Chạy giao diện | **http://127.0.0.1:5173** |

Đợi terminal Backend hiện `Application startup complete` rồi mở http://127.0.0.1:5173.

Tắt: đóng các terminal đó hoặc **Terminal → Terminate Task**. PostgreSQL vẫn chạy trong Docker (tắt bằng `docker compose -f docker/docker-compose.yml stop`).

Không dùng VS Code thì mở 3 cửa sổ PowerShell và chạy mỗi cửa sổ một lệnh:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/start-ollama.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev/start-backend.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev/start-frontend.ps1
```

## 5. Tài khoản và quyền Admin

- Vào http://127.0.0.1:5173 → **Đăng ký** để tạo tài khoản (vai trò USER).
- Muốn xem trang **Cơ sở dữ liệu** thì tài khoản phải là ADMIN. Cấp quyền cho tài khoản đã đăng ký:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/make-admin.ps1 ten@email.com
```

  Sau đó đăng xuất, đăng nhập lại: thanh bên có thêm mục **Cơ sở dữ liệu**. Hạ quyền: thêm `-Revoke` vào cuối lệnh.
- Cách khác của CAP1: đặt `LOCAL_AUTH_ADMIN_EMAIL` và `LOCAL_AUTH_ADMIN_PASSWORD` (mật khẩu đủ dài) trước lần chạy đầu tiên, khi cơ sở dữ liệu chưa có tài khoản nào; backend tự tạo tài khoản ADMIN đó.

## 6. Build bản production (không bắt buộc)

```powershell
cd frontend
npm run build
```

Kết quả ở `frontend/dist`. Khi triển khai cần một web server (ví dụ nginx) phục vụ `dist` và chuyển `/api` sang backend.

## 7. Kiểm tra nhanh sau khi chạy

```powershell
cd backend
.venv\Scripts\python.exe -m pytest tests -q
cd ..\frontend
npx tsc -b
```

## 8. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `Không bật được PostgreSQL` | Mở Docker Desktop, đợi chạy xong rồi nhấn lại Ctrl+Shift+B |
| `Chưa cài Ollama` | Cài Ollama, mở lại VS Code để PATH cập nhật |
| Cổng 8000 hoặc 5173 đã bị chiếm | Tắt chương trình đang dùng cổng đó (một bản backend/frontend khác đang chạy) |
| Trang báo chưa kết nối mô hình | Xem terminal Ollama; lần đầu đang tải mô hình thì đợi tải xong |
| Muốn đổi cấu hình (cơ sở dữ liệu, mô hình…) | Đặt biến môi trường trước khi chạy hoặc ghi vào `backend/.env`; giá trị mặc định nằm đầu file `scripts/dev/start-backend.ps1` |

Mô tả phần đã tích hợp và giới hạn hiện tại: `docs/C1SE27_INTEGRATION_VI.md`.
