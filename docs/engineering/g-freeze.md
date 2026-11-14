# G-freeze — đóng băng cấu hình thực nghiệm (2026-11-14)

Điều kiện đóng băng: W-A, W-B (và W-C, W-D, sửa budget) đã gộp vào `s3/integration`; full suite xanh (1101 passed, 1 skipped, 7 xfailed, PG test thật, PROVIDER=fake); ruff/mypy không có lỗi mới so với baseline; import-linter 3 kept/0 broken.

Mã: `s3/integration` tại commit ghi bởi `git rev-parse HEAD` lúc chạy pilot (commit đóng băng: xem tag/ghi chú Owner; chưa tạo tag, chưa merge vào nhánh của Owner).

## Điều kiện pilot
Chỉ A, B0, B, C với P/N/O đã nối thật (`research/pipeline.py:_flags`). Router và Project Memory chưa nối vào đường xử lý, chưa đánh giá (không ghi là kết quả âm).

## Cấu hình
| Mục | Giá trị |
|---|---|
| Hồ sơ | `IMPLEMENTATION_PROFILE=dev` chỉ trong tiến trình thí nghiệm; mặc định `m0` không đổi |
| Condition review | `REVIEW_PIPELINE_CONDITION` (A mặc định; C cho thí nghiệm) |
| Chính sách ngữ cảnh | C: `adaptive_qwen` (mặc định của C); A: không ghi đè |
| Trần token đầu ra CHUNG | `MAX_OUTPUT_TOKENS=700` và `TASK_PLAN_MAX_OUTPUT_TOKENS=700` cho mọi điều kiện A/B0/B/C (giá trị mặc định hiện tại, đọc từ `core/config.py`); không đổi giữa điều kiện, không tốn thêm lượt gọi |
| Trần ngữ cảnh / run | `max_context_tokens=3000`, `max_run_tokens=12000`, `task_top_k=6`, `planning_top_k=3`, `retrieval_min_score=0.18`, `retry_limit=1` |
| config_hash | phụ thuộc môi trường. Tính ở môi trường dev bằng `RuntimeConfig.from_env().config_hash()`: `ffd53adf6751cd42` (dev, môi trường kiểm thử BE), `0d89c82b20b869fb` (m0). Probe 14/11 với PROVIDER=ollama, profile dev: `3177e07680d9e474`. Ghi lại giá trị thực từ `run_started.config_hash` của từng lần chạy; dùng làm khóa so sánh |
| Model sinh | `qwen3:4b` qua Ollama, digest `359d7dd4bcda...` (cắt 12 ký tự), `think=false`, temperature 0.1 (`LOCAL_LLM_TEMPERATURE`) |
| Model embedding | `nomic-embed-text:latest`, digest `0a109f422b47...` |
| Giới hạn thí nghiệm | Ollama: ≤100 lượt, ≤20 phút, một inference tại một thời điểm, ResourceGuard bật |
| Số lượt tối thiểu/yêu cầu | A: 1; C: 4 (extraction, plan, mỗi task 1, synthesize), yêu cầu N task: N+3 (+1 mỗi lần sửa plan) |

## Quy tắc
- Không đổi cấu hình trên khi đang chạy pilot; thay đổi nào cũng phải ghi lại và tính lại config_hash.
- Kết quả đo là số đếm thô trên tập tự dựng; không suy diễn từ chênh lệch nhỏ.
- GĐ1: pilot A 30 yêu cầu, rồi C; dừng sớm nếu 3 yêu cầu đầu của C đều FAILED.
## Cập nhật 2026-11-14 (GĐ1 bước 2): thinking
- `think=false` được gửi trong mọi lượt Ollama (`providers/ollama.py`) nhưng **không có tác dụng** với qwen3:4b digest `359d7dd4bcda` trên Ollama 0.40.13: model là bản luôn suy nghĩ (template luôn mở `<think>`), lập luận đi vào `content`, không có trường `thinking`, `eval_count` không giảm. Đã thử thêm `/no_think` ở system và user, và chế độ `raw` với khối `<think></think>` rỗng: đều vẫn suy nghĩ (4 lượt thăm dò, tính vào quota).
- Hệ quả: thinking BẬT ở mọi đường A, B, C, planning, normalization như nhau (cùng cấu hình, không thiên vị điều kiện nào). Với lượt có `format`/schema, ngữ pháp ép JSON nên không thấy thinking trong đầu ra; với lượt văn xuôi (A) thinking tiêu hết trần 700 token.
- Cắt đầu ra được đánh dấu bằng `done_reason == "length"` (cột `truncated` trong summary.csv) cho mọi lượt.
- `A_run1` chỉ là shakedown (25 yêu cầu, 16/25 cắt, ~24 s/lượt), KHÔNG dùng làm kết quả.
- Trần token giữ 700 cho mọi điều kiện (chưa đổi).
