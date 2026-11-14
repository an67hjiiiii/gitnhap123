# ADR 0004: Fast lane và phân công worker

## Context

Quy trình làm việc được mô tả theo các lớp T0, T1, T2 và các model Luna/Sol.
Trong repository hiện có, chưa tìm thấy tài liệu chuẩn xác định ý nghĩa
đầy đủ hoặc cách tự động định tuyến các lớp và model này.

## Decision

Phạm vi yêu cầu mô tả T0 là chạy test module, T1 là chạy test liên quan,
và T2 là chạy test liên quan cùng full suite và rà soát diff.
Yêu cầu cũng nêu Luna/Sol routing, tối đa 4 worker và một worktree mỗi worker.
Quyết định vận hành này chưa xác minh trong repository; không suy diễn
thêm model cụ thể, ngưỡng phân loại hay cơ chế định tuyến.

## Consequences

Các tiêu chí test T0/T1/T2 cùng worker routing không thể được xem là contract
đã kiểm chứng của mã nguồn hiện tại. Chi tiết chưa được chứng minh được ghi
là chưa xác minh cho đến khi có nguồn chuẩn trong repository.

## Status

Chưa xác minh; nội dung là ghi nhận giới hạn chứng cứ, không phải quyết định
đã triển khai.

