# ADR 0002: PostgreSQL authoritative, Qdrant derived

## Context

PostgreSQL lưu dữ liệu ứng dụng có thẩm quyền; vector search dùng chỉ mục
Qdrant embedded/local có thể được tạo lại từ dữ liệu nguồn.
Danh tính embedder có backend, model, dimension, embedding version,
normalization version và digest tùy chọn.

Manifest JSON nằm cạnh thư mục chỉ mục, giữ identity cùng cờ empty và
payload completeness. Thiếu manifest không được xem là chỉ mục rỗng.

## Decision

Xem PostgreSQL là authoritative và Qdrant là derived index.
Ghi identity manifest để so khớp cấu hình chỉ mục.
Trạng thái được tính là `COMPATIBLE`, `EMPTY`, `LEGACY_UNVERIFIED` hoặc
`INCOMPATIBLE`. Manifest vắng mặt cho trạng thái legacy chưa xác minh;
identity khác nhau cho trạng thái không tương thích.
Lỗi identity không tương thích được ánh xạ thành `INDEX_INCOMPATIBLE`
và HTTP 503 trong Review API.

## Consequences

Metadata cho phép phân biệt chỉ mục tương thích, rỗng, cũ thiếu xác minh
và không tương thích mà không coi thiếu manifest là dữ liệu rỗng.
PostgreSQL vẫn là nguồn dữ liệu chuẩn khi chỉ mục dẫn xuất không dùng được.
Quy trình dựng lại và vận hành khôi phục cụ thể: chưa xác minh.

## Status

Accepted; căn cứ là `backend/app/retrieval/index_identity.py`,
`backend/app/storage/vector_store.py` và `backend/app/api/review.py`.

