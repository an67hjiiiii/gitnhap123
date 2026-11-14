# ADR 0001: Modular monolith

## Context

Backend là ứng dụng FastAPI với các package cho API, review, adapters,
retrieval, storage, providers và orchestration. Review cần có ranh giới rõ
để domain không phụ thuộc trực tiếp vào HTTP hay hạ tầng.

`backend/pyproject.toml` khai báo import-linter contracts cấm `app.review`
phụ thuộc vào API, adapters và infrastructure; cấm pipeline layers phụ thuộc
vào Review/API; và cấm adapters phụ thuộc HTTP layer.

Review domain định nghĩa `ReviewEngine` port trong `app.review.engine`.
Adapters cung cấp phần triển khai nối domain với pipeline.

## Decision

Tổ chức backend như modular monolith phân lớp trong một ứng dụng.
Giữ các module qua seam rõ ràng và ưu tiên kiểm tra seam bằng contracts.
Review domain chỉ nhận engine qua `ReviewEngine`, không import adapter cụ thể.
HTTP router, adapters và hạ tầng được đặt ngoài domain Review.

## Consequences

Import-linter mô tả và kiểm tra các hướng phụ thuộc được phép.
Port cho phép thay engine mà không làm domain phụ thuộc lớp giao vận.
Các contract hiện có giới hạn ba nhóm phụ thuộc nêu trên.
Chi tiết triển khai hoặc mức độ kiểm tra seam ngoài các contract này:
chưa xác minh.

## Status

Accepted; căn cứ là `backend/pyproject.toml` và `backend/app/review/engine.py`.

