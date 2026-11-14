# Chạy condition C cho thí nghiệm

Mặc định hồ sơ `IMPLEMENTATION_PROFILE=m0` chỉ cho phép condition A; không đổi mặc định này. Các lượt chạy API bình thường luôn dùng A.

Chỉ trong tiến trình thí nghiệm, đặt:

```
IMPLEMENTATION_PROFILE=dev
REVIEW_PIPELINE_CONDITION=C
PROVIDER=ollama
REVIEW_CONTEXT_POLICY=adaptive_qwen   # tùy chọn; C mặc định đã dùng adaptive_qwen
```

Nếu thiếu hồ sơ dev, finding là `UNDETERMINED` kèm `task.failed` với `error_type=CONDITION_NOT_AVAILABLE`.

Số lượt model tối thiểu cho một yêu cầu ở C: extraction 1 + plan 1 + mỗi task 1 + synthesize 1 (yêu cầu có 1 task = 4 lượt, 3 task = 6 lượt); thêm 1 lượt cho mỗi lần sửa plan. Đo ngày 14/11 với qwen3:4b: lượt đầu 10-16 giây (nạp model), các lượt sau khoảng 3-10 giây.

Chẩn đoán lỗi: event `pipeline.trace` có `condition`, `config_hash`, kết quả planning retrieval/normalization; `task.failed.error_type` là mã ổn định: `PLAN_REJECTED`, `PROVIDER_LIMIT`, `CONDITION_NOT_AVAILABLE`, `PIPELINE_RUN_FAILED`, `UNKNOWN`. Chi tiết lỗi chỉ có trong log máy chủ.