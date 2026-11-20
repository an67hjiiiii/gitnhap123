# Hướng dẫn vận hành OrchestrIQ Studio trên máy chủ (Docker)

Dành cho người quản trị hệ thống của tổ chức. Máy phát triển của nhóm dùng cách chạy khác (Ctrl+Shift+B, xem `HUONG_DAN_CHAY_DU_AN.md`); bản máy chủ chạy riêng, không đụng CSDL phát triển.

## 1. Yêu cầu

- Docker Desktop (Windows) hoặc Docker Engine + Compose (Linux).
- RAM tối thiểu 16 GB cho mô hình `qwen3:4b` (8 GB chạy được nhưng chậm). GPU NVIDIA tùy chọn.
- Ollama cài trên máy chủ, hoặc chạy Ollama trong Docker (`-OllamaInDocker` / `--profile ollama`).
- Ổ đĩa: khoảng 10 GB cho ảnh Docker và mô hình, cộng dung lượng tài liệu.

## 2. Cài đặt

Trong thư mục gốc dự án:

```powershell
powershell -ExecutionPolicy Bypass -File docker/install.ps1 -DryRun          # chỉ kiểm tra phần cứng, không đổi gì
powershell -ExecutionPolicy Bypass -File docker/install.ps1                  # cài: cổng 8080, dự án Docker "orchestriq"
powershell -ExecutionPolicy Bypass -File docker/install.ps1 -WebPort 18080 -Project orchestriq-thu   # bản thử bên cạnh bản thật
```

Linux: `bash docker/install.sh [--dry-run] [--port=8080] [--project=orchestriq]` (Ollama chạy trong Docker).

Bộ cài kiểm tra Docker, đo RAM/CPU/GPU, gợi ý mô hình, tạo `docker/.env` với mật khẩu CSDL ngẫu nhiên (không in ra màn hình, không đưa lên Git), dựng ảnh, bật dịch vụ, tải mô hình và chờ `/api/health`.

Sau khi cài: mở `http://<máy chủ>:8080`, tạo tài khoản đầu tiên, rồi cấp quyền quản trị:

```powershell
docker compose -p orchestriq -f docker/docker-compose.server.yml exec -T postgres psql -U orchestriq -d orchestriq -c "UPDATE users SET role='ADMIN' WHERE lower(email)=lower('quantri@congty.vn');"
```

Đã chạy thật trên máy của nhóm (20/11/2026, dự án `orchestriq-thu`, cổng 18080): lần 1 lỗi khi dựng giao diện (`npm ci` ENETUNREACH do mạng Docker không có IPv6, đã sửa trong `frontend/Dockerfile`); lần 2 cài xong trong 101 giây với ảnh backend đã có sẵn từ lần 1. Chưa đo thời gian cài trên máy sạch.

## 3. Bật, tắt, xem nhật ký

```powershell
cd docker
docker compose -p orchestriq -f docker-compose.server.yml ps
docker compose -p orchestriq -f docker-compose.server.yml logs -f backend
docker compose -p orchestriq -f docker-compose.server.yml stop        # tắt, giữ dữ liệu
docker compose -p orchestriq -f docker-compose.server.yml start
```

Không dùng `down -v`: lệnh này xóa ổ dữ liệu (CSDL, chỉ mục vector).

## 4. Sao lưu

Hai phần cần sao lưu: CSDL PostgreSQL (tài khoản, tài liệu, đoạn, lượt chạy, tổ chức) và ổ `vectors` (chỉ mục Qdrant, dựng lại được từ CSDL nhưng mất thời gian).

```powershell
cd docker
$d = Get-Date -Format yyyyMMdd-HHmm
docker compose -p orchestriq -f docker-compose.server.yml exec -T postgres pg_dump -U orchestriq -d orchestriq --clean --if-exists > "saoluu-$d.sql"
# chỉ mục vector: tạm dừng backend (Qdrant nhúng chỉ cho một tiến trình), nén ổ, bật lại
docker compose -p orchestriq -f docker-compose.server.yml stop backend
docker run --rm -v orchestriq_vectors:/data -v "${PWD}:/b" alpine tar czf "/b/vectors-$d.tgz" -C /data .
docker compose -p orchestriq -f docker-compose.server.yml start backend
```

Lên lịch: Windows Task Scheduler hoặc cron chạy các lệnh trên mỗi đêm; giữ ít nhất 7 bản, chép một bản ra máy khác. Tệp sao lưu chứa dữ liệu nội bộ: lưu ở nơi có phân quyền.

## 5. Khôi phục

Thử khôi phục định kỳ vào một CSDL tạm trước, không ghi đè dữ liệu đang dùng:

```powershell
docker compose -p orchestriq -f docker-compose.server.yml exec -T postgres createdb -U orchestriq khoiphuc_thu
Get-Content saoluu-YYYYMMDD-HHMM.sql | docker compose -p orchestriq -f docker-compose.server.yml exec -T postgres psql -q -U orchestriq -d khoiphuc_thu
docker compose -p orchestriq -f docker-compose.server.yml exec -T postgres psql -U orchestriq -d khoiphuc_thu -c "select count(*) from users;"
docker compose -p orchestriq -f docker-compose.server.yml exec -T postgres dropdb -U orchestriq khoiphuc_thu
```

Đã chạy thật 20/11: bản sao lưu 63 KB, khôi phục vào CSDL tạm đủ 24 bảng.

Khôi phục thật (sau sự cố): dừng backend, chạy lệnh `psql` như trên vào CSDL `orchestriq` (tệp có `--clean` nên ghi đè bảng), giải nén `vectors-*.tgz` vào ổ `orchestriq_vectors`, bật backend.

## 6. Nâng cấp

```powershell
git pull                                        # lấy mã mới (nhánh do nhóm phát hành)
# sao lưu trước (mục 4), rồi:
cd docker
docker compose -p orchestriq -f docker-compose.server.yml up -d --build
```

Backend tự cập nhật bảng (`alembic upgrade head`) trước khi nhận yêu cầu. Các bản cập nhật bảng của nhóm chỉ thêm bảng/cột, không xóa dữ liệu; vẫn cần sao lưu trước.

## 7. Nhận dạng chữ (OCR)

Ảnh Docker backend có sẵn Tesseract kèm gói tiếng Việt: ảnh chụp và PDF scan được nhận dạng khi tải lên. Chạy thật 20/11 trên ảnh chụp văn bản tiếng Việt: thân văn bản đúng 5/5 cụm từ kiểm tra; dòng tiêu đề viết hoa sai vài dấu (NGHỈ → NGHĨ). Văn bản scan mờ, nghiêng, viết tay chưa được thử.

## 8. Đăng nhập bằng tài khoản tổ chức (tùy chọn, tắt mặc định)

Thêm vào `docker/.env` (rồi `up -d`):

```
OIDC_PROVIDERS=google            # hoặc microsoft, hoặc google,microsoft
OIDC_GOOGLE_CLIENT_ID=...
OIDC_GOOGLE_CLIENT_SECRET=...
OIDC_MICROSOFT_CLIENT_ID=...
OIDC_MICROSOFT_CLIENT_SECRET=...
OIDC_MICROSOFT_TENANT=<mã tenant của tổ chức>
OIDC_REDIRECT_BASE=https://studio.congty.vn
OIDC_ALLOWED_DOMAINS=congty.vn
COOKIE_SECURE=true
```

Backend đọc cả tệp `docker/.env` (`env_file` trong compose). Đăng ký ứng dụng ở Google Cloud Console / Microsoft Entra với địa chỉ chuyển hướng `https://studio.congty.vn/api/auth/oidc/<google|microsoft>/callback`. Đã kiểm thử với nhà cung cấp giả lập; chưa thử với tài khoản thật.

## 9. HTTPS và mạng nội bộ

Đặt máy chủ sau reverse proxy có chứng chỉ (nginx, Caddy, IIS ARR) và đặt `COOKIE_SECURE=true`. Không mở cổng PostgreSQL ra ngoài (compose máy chủ không mở). Ollama chỉ nên nghe trong mạng nội bộ.

## 10. Giám sát

- Sức khỏe: `GET /api/health` (trả `ok`, kết nối mô hình).
- Cổng quản trị trong ứng dụng (tài khoản ADMIN): người dùng, nhật ký, cấu hình AI, tình trạng dịch vụ.
- Dung lượng: `docker system df -v`; theo dõi ổ `orchestriq_pgdata`, `orchestriq_vectors`.
