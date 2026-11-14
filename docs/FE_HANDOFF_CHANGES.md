# Bàn giao hợp đồng Review cho FE

## Đã thay đổi hợp đồng

| JSON path / enum | Thay đổi |
| --- | --- |
| `CaseStatus` | Enum `DRAFT`, `CONFIRMING`, `READY`, `RUNNING`, `PARTIAL`, `COMPLETE`, `FAILED`. |
| `Verdict` | Enum `SATISFIED`, `PARTIAL`, `NOT_FOUND`, `DEVIATES`, `UNDETERMINED`, `SKIPPED_BUDGET`. |
| `JobState` | Enum `QUEUED`, `RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`, `CANCELLED`; trạng thái có thể là `PARTIAL` khi lượt chạy hoàn tất nhưng còn yêu cầu bị bỏ qua. |
| `Decision` | Enum `NONE`, `ACCEPT`, `REJECT`, `EDIT`. |
| `ErrorBody.code` | Enum mã lỗi ổn định; xem đầy đủ trong `contracts/review/labels.vi.json`. |
| `route.decided.data.reasons[]` | Các chuỗi tự do được thay bằng `{code, params}`. |
| `verdict.conflict`, `verdict.answer_inconsistent`, `verdict.slots_missing` | Có `code` và `params`; không còn `detail` văn xuôi. |
| `task.failed.data` | Có `error_type` ổn định và thông báo chung, không gửi chi tiết ngoại lệ. |
| `GET /findings/{id}/decision` | Không tìm thấy finding trả `FINDING_NOT_FOUND`, thay cho `CASE_NOT_FOUND`. |
| HTTP lỗi non-review | Trả `{code, message}`; lỗi không rõ được chuẩn hóa thành mã chung. |
| `GET /cases/{id}/export` | Markdown dùng nhãn tiếng Việt; bằng chứng vẫn được giữ. |

## Tích hợp giao diện

Đọc `contracts/review/labels.vi.json` làm nguồn nhãn. Ánh xạ `verdict`, `case_status`, `job_state`, `decision` bằng giá trị enum; ánh xạ `errors` bằng `code`. Không hiển thị `message` từ máy chủ. Với mã chưa biết, dùng câu dự phòng chung và giữ mã để ghi nhận.

Khi xử lý lỗi, lấy `what` và `todo` để hiển thị hai câu hướng dẫn. Với HTTP 429, đọc `Retry-After` và chờ đủ số giây trước khi thử lại.

Với SSE, hiển thị tiến trình bằng `events[eventName]`; unknown event dùng thông báo chung. Gửi `Last-Event-ID` khi nối lại. Ưu tiên SSE thay vì polling `GET /runs/{id}` vì polling cũng tính vào giới hạn request.

`route.decided.data.reasons` là danh sách mã cùng tham số. Với các event verdict, dùng `code` để chọn thông điệp, còn `params` có thể dùng để bổ sung chi tiết có cấu trúc. `pipeline.trace` cũng được phát ở condition A, khi một số trường chi tiết là `null`.

## Giới hạn và hành vi

- `task_budget` và `pipeline.trace` mô tả ngân sách/tiến trình; không diễn giải trace như kết quả cuối.
- `verdict.slots_missing` báo những chi tiết còn thiếu trong `params.missing_slots`.
- Giới hạn mặc định: `request_text` 20.000 ký tự; requirement và `edited_text` 2.000; tối đa 100 requirement mỗi case. Các giới hạn nội dung có thể cấu hình bằng `REVIEW_MAX_REQUEST_CHARS`, `REVIEW_MAX_REQUIREMENT_CHARS`, `REVIEW_MAX_REQUIREMENTS_PER_CASE`.
- Budget gửi lên bị chặn theo `REVIEW_MAX_REQUIREMENTS` (mặc định 100), `REVIEW_MAX_SECONDS` (3600), `REVIEW_MAX_TOKENS`, `REVIEW_MAX_MODEL_CALLS`; phản hồi trạng thái job echo budget hiệu lực.
- Mỗi người dùng mặc định có 2 lần bắt đầu chạy/phút và 60 request Review khác/phút. Cấu hình bằng `REVIEW_RATE_RUNS_PER_MIN`, `REVIEW_RATE_READS_PER_MIN`; 429 có `Retry-After`.
- ID proposal fake có dạng `<case>:req-n`.
- `PDF_NO_TEXT`, `UNSUPPORTED_DOCUMENT_TYPE`, `UTF8_TEXT_REQUIRED`, `DOCUMENT_EXTRACTION_FAILED`, `DERIVED_INDEX_FAILED` là mã lỗi tải tài liệu/chỉ mục. Định dạng hỗ trợ: TXT, MD, PDF.

## Biến môi trường trong tài liệu hợp đồng

| Biến | Ý nghĩa |
| --- | --- |
| `REVIEW_MAX_REQUEST_CHARS` | Độ dài tối đa của request text. |
| `REVIEW_MAX_REQUIREMENT_CHARS` | Độ dài tối đa requirement và edited text. |
| `REVIEW_MAX_REQUIREMENTS_PER_CASE` | Số requirement tối đa mỗi case. |
| `REVIEW_MAX_REQUIREMENTS` | Trần số requirement xử lý trong một lượt chạy. |
| `REVIEW_MAX_SECONDS` | Trần thời gian lượt chạy. |
| `REVIEW_MAX_TOKENS` | Trần token nếu cấu hình. |
| `REVIEW_MAX_MODEL_CALLS` | Trần số lần gọi model nếu cấu hình. |
| `REVIEW_RATE_RUNS_PER_MIN` | Giới hạn bắt đầu lượt chạy mỗi phút. |
| `REVIEW_RATE_READS_PER_MIN` | Giới hạn request Review khác mỗi phút. |

`task_budget`, `pipeline.trace`, giới hạn body và các trường trên được giữ theo hợp đồng hiện hành; FE nên đọc OpenAPI snapshot thay vì tự suy đoán thêm trường.
