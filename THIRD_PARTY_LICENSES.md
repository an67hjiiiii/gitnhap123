# Giấy phép thư viện bên thứ ba

Tệp này được tạo tự động bằng `scripts/dev/licenses.py` từ `frontend/package-lock.json` và môi trường `backend/.venv`.
Chạy lại script mỗi khi đổi thư viện. Dòng **in đậm** là giấy phép cần đọc kỹ điều khoản trước khi bán (4 dòng).

## Thành phần chạy kèm

| Thành phần | Vai trò | Giấy phép |
|---|---|---|
| Ollama | máy chủ chạy mô hình cục bộ | MIT |
| qwen3:4b (Qwen3) | mô hình ngôn ngữ, tải qua Ollama | Apache-2.0 |
| nomic-embed-text | mô hình embedding, tải qua Ollama | Apache-2.0 |
| PostgreSQL 16 | cơ sở dữ liệu (ảnh Docker postgres:16) | PostgreSQL License |
| Docker Desktop | chạy PostgreSQL; khách tự cài | Điều khoản Docker (miễn phí cho tổ chức nhỏ, doanh nghiệp lớn cần gói trả phí) |

## Giao diện (JavaScript, 14 gói được phát hành)

| Gói | Phiên bản | Giấy phép |
|---|---|---|
| @fontsource-variable/inter-tight | 5.2.5 | OFL-1.1 |
| @fontsource/be-vietnam-pro | 5.3.0 | OFL-1.1 |
| @gsap/react | 2.1.2 | **SEE LICENSE AT https://gsap.com/standard-license** |
| @phosphor-icons/react | 2.1.10 | MIT |
| cookie | 1.1.1 | MIT |
| gsap | 3.15.0 | **Standard 'no charge' license: https://gsap.com/standard-license.** |
| lenis | 1.3.27 | MIT |
| lucide-react | 0.511.0 | ISC |
| react | 19.2.8 | MIT |
| react-dom | 19.2.8 | MIT |
| react-router | 7.18.4 | MIT |
| react-router-dom | 7.18.4 | MIT |
| scheduler | 0.27.0 | MIT |
| set-cookie-parser | 2.7.3 | MIT |

## Backend (Python, 41 gói)

| Gói | Phiên bản | Giấy phép |
|---|---|---|
| Mako | 1.4.3 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT License |
| SQLAlchemy | 2.1.8 | MIT |
| alembic | 1.20.1 | MIT |
| annotated-doc | 0.0.6 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| certifi | 2026.10.23 | Mozilla Public License 2.0 (MPL 2.0) |
| click | 8.5.1 | BSD-3-Clause |
| fastapi | 0.162.4 | MIT |
| filelock | 4.2.10 | MIT |
| fsspec | 2026.9.0 | BSD-3-Clause |
| grpcio | 1.85.1 | Apache-2.0 |
| h11 | 0.16.0 | MIT License |
| hf-xet | 1.8.0 | Apache-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD License |
| huggingface_hub | 1.33.0 | Apache Software License |
| idna | 3.20 | BSD-3-Clause |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| portalocker | 4.4.2 | BSD-3-Clause |
| protobuf | 7.36.2 | 3-Clause BSD License |
| psutil | 7.2.2 | BSD-3-Clause |
| psycopg | 3.3.8 | **LGPL-3.0-only** |
| psycopg-binary | 3.3.8 | **LGPL-3.0-only** |
| pydantic | 2.14.3 | MIT |
| pydantic_core | 2.50.4 | MIT |
| pypdf | 6.21.4 | BSD-3-Clause |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.33 | Apache-2.0 |
| qdrant-client | 1.20.0 | Apache Software License |
| starlette | 1.10.0 | BSD-3-Clause |
| tokenizers | 0.22.2 | Apache Software License |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| typing-inspection | 0.4.5 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.6 | Apache-2.0 |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |

## Ghi chú về các dòng cần đọc kỹ

- **GSAP, @gsap/react** (giấy phép Standard "no charge" của GSAP/Webflow): cho phép dùng miễn phí trong sản phẩm thương mại;
  điều khoản cấm dùng trong công cụ cạnh tranh với trình dựng hoạt ảnh trực quan của Webflow. OrchestrIQ Studio là công cụ phân tích
  tài liệu, không thuộc loại đó. Đọc lại https://gsap.com/standard-license trước mỗi lần phát hành.
- **psycopg, psycopg-binary** (LGPL-3.0): được dùng như thư viện, không sửa mã nguồn, cài riêng qua pip nên khách có thể thay bản khác.
  Khi phân phối cần giữ thông báo giấy phép và chỉ nguồn tải (https://www.psycopg.org).
- Phông chữ Inter Tight và Be Vietnam Pro (OFL-1.1): được nhúng và bán kèm phần mềm; không được bán riêng phông chữ.
