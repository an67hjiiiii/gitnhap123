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
- Khi đã có một ADMIN, mọi việc còn lại làm trên web ở trang **Người dùng** (nhóm Quản trị trên thanh bên): tạo tài khoản cho nhân viên (để trống mật khẩu thì hệ thống tạo mật khẩu tạm, chỉ hiện một lần), cấp/bỏ quyền quản trị, khóa/mở khóa (khóa thì người đó bị đăng xuất ngay, dữ liệu giữ nguyên), đặt lại mật khẩu tạm, đăng xuất mọi phiên. Hệ thống không cho tự hạ quyền hay tự khóa chính mình, và luôn giữ ít nhất một quản trị viên đang hoạt động. Mọi thao tác được ghi vào nhật ký hoạt động (bảng `studio_activity`). API: `/api/admin/users`.

## 6. Bản phát hành và chạy kiểu sản phẩm

- Chạy giao diện bằng bản build tối ưu (như khi bàn giao), ở http://127.0.0.1:4173; backend vẫn chạy như mục 4:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts/dev/start-preview.ps1          # thêm -Rebuild để build lại
  ```
- Đóng gói bản phát hành (chạy test, kiểm tra kiểu, build, nén thành `release/OrchestrIQ-Studio-<ngày>-<commit>.zip` kèm tệp `.sha256`). Gói không chứa môi trường ảo, `node_modules`, dữ liệu người dùng hay tệp `.env`:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts/dev/build-release.ps1          # thêm -SkipTests nếu vừa chạy test
  ```
  Người nhận giải nén, chạy `scripts/dev/setup.ps1` một lần, sau đó nhấp đúp `MO_ORCHESTRIQ.cmd` (xem `CAI_DAT.txt` trong gói).
- Bảng mới của các chức năng phân tích (`studio_reports`) được tạo tự động bằng Alembic khi backend khởi động.

### Chạy không cần VS Code (máy khách)

- Nhấp đúp `MO_ORCHESTRIQ.cmd` ở thư mục gốc: mở 3 cửa sổ (Ollama, Backend, Giao diện bản build), chờ backend sẵn sàng rồi tự mở http://127.0.0.1:4173/studio. Cái nào đã chạy sẵn thì không mở lại.
- Tắt: nhấp đúp `TAT_ORCHESTRIQ.cmd` (dừng backend và giao diện; Ollama, PostgreSQL để nguyên). Tắt cả hai: `scripts/dev/stop-all.ps1 -All`.

### Sao lưu và khôi phục dữ liệu

- Sao lưu đủ (CSDL + chỉ mục vector) vào `backups/OrchestrIQ-backup-<thời điểm>.zip` kèm `.sha256`; cần tắt backend trước:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts/dev/backup.ps1
  powershell -ExecutionPolicy Bypass -File scripts/dev/backup.ps1 -DatabaseOnly   # chỉ CSDL, làm được khi đang chạy
  ```
- Khôi phục (tự sao lưu dữ liệu hiện tại trước, kiểm tra SHA-256, chỉ mục cũ được đổi tên chứ không xóa, hỏi xác nhận):
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts/dev/restore.ps1 -From backups\OrchestrIQ-backup-....zip
  ```

### Chạy trên máy chủ công ty (Docker)

- Chép `docker/server.env.example` thành `docker/.env`, đặt `POSTGRES_PASSWORD` (chữ và số, từ 16 ký tự). Rồi:
  ```powershell
  cd docker
  docker compose -f docker-compose.server.yml up -d --build
  ```
  Mở http://<máy chủ>:8080. Gồm giao diện (nginx, chuyển `/api` sang backend), backend (Python 3.12, tự `alembic upgrade head`), PostgreSQL 16. Dữ liệu nằm trong volume `pgdata` và `vectors`.
- Mô hình: mặc định gọi Ollama cài trên máy chủ qua `host.docker.internal:11434` (trên Linux đặt `OLLAMA_HOST=0.0.0.0` cho Ollama). Hoặc chạy Ollama trong Docker: thêm `--profile ollama`, đặt `OLLAMA_BASE_URL=http://ollama:11434`, rồi tải `qwen3:4b` và `nomic-embed-text` bằng `docker compose -f docker-compose.server.yml exec ollama ollama pull <tên>`. Máy chủ có GPU NVIDIA thì thêm `-f docker-compose.gpu.yml` (cần driver NVIDIA + NVIDIA Container Toolkit): đo trên RTX 3060 Laptop, một câu hỏi ngắn mất 88 giây khi chạy bằng CPU, còn 2 giây với GPU khi mô hình đã nạp sẵn (lần đầu 54 giây vì phải nạp mô hình). Đây là một lần đo thử, không phải benchmark.
- Truy cập qua HTTPS (reverse proxy có chứng chỉ) thì đặt `COOKIE_SECURE=true` để cookie phiên chỉ gửi qua kết nối mã hóa.
- Sao lưu CSDL của bản máy chủ (chạy trên chính máy chủ Windows có PowerShell; khôi phục dùng `restore.ps1` với cùng tham số):
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts/dev/backup.ps1 -DatabaseOnly -Container orchestriq-postgres-1 -Database orchestriq -User orchestriq -BackendPort 0
  ```

### Giấy phép thư viện bên thứ ba

- `THIRD_PARTY_LICENSES.md` ở thư mục gốc liệt kê giấy phép của mọi thư viện được phát hành kèm, tạo bằng `backend/.venv/Scripts/python.exe scripts/dev/licenses.py` (build-release.ps1 tự chạy). Dòng in đậm cần đọc kỹ trước khi bán (hiện có GSAP và psycopg; ghi chú ở cuối tệp).

## 7. Kiểm tra nhanh sau khi chạy

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/smoke-test.ps1    # backend, CSDL, Ollama và mô hình, giao diện, API phân tích
cd backend
.venv\Scripts\python.exe -m pytest tests -q
cd ..\frontend
npx tsc -b
```

Hướng dẫn dùng từng chức năng: `docs/HUONG_DAN_SU_DUNG.md`.

## 8. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| Docker Desktop chưa mở | Script tự mở Docker Desktop và chờ tối đa 2 phút. Nếu vẫn báo lỗi, mở Docker Desktop, đợi "Engine running" rồi nhấn lại Ctrl+Shift+B |
| `ports are not available ... 55435` | Windows (Hyper-V/WSL) đang giữ chỗ dải cổng chứa 55435. Script tự chuyển PostgreSQL sang cổng trống khác (ví dụ 54329) và báo trong terminal Backend. Muốn cố định cổng: đặt biến `CAP1_PG_PORT` |
| `Không tìm thấy Ollama` | Cài Ollama rồi mở lại VS Code. Script tìm ollama.exe trong PATH, `%LOCALAPPDATA%\Programs\Ollama`, `Program Files\Ollama`, thư mục `.runtime\ollama` của dự án, hoặc đường dẫn trong biến `OLLAMA_EXE` |
| Cổng 8000 hoặc 5173 đã bị chiếm | Tắt chương trình đang dùng cổng đó (một bản backend/frontend khác đang chạy) |
| Trang báo chưa kết nối mô hình | Xem terminal Ollama; lần đầu đang tải mô hình thì đợi tải xong |
| Muốn đổi cấu hình (cơ sở dữ liệu, mô hình…) | Đặt biến môi trường trước khi chạy hoặc ghi vào `backend/.env`; giá trị mặc định nằm đầu file `scripts/dev/start-backend.ps1` |

Mô tả phần đã tích hợp và giới hạn hiện tại: `docs/C1SE27_INTEGRATION_VI.md`.
