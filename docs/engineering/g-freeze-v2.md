# G-freeze v2 — cấu hình thực nghiệm chính (DỰ THẢO, chờ Owner duyệt trước khi chạy)

Thay thế `g-freeze.md` cho lần chạy chính; `g-freeze.md` giữ làm lịch sử (bản thinking).

## Cấu hình đóng băng
| Mục | Giá trị |
|---|---|
| Model | `qwen3:4b-instruct-2507-q4_K_M`, digest `0edcdef34593` (không-thinking, `LOCAL_LLM_MODEL` chỉ trong tiến trình thí nghiệm) |
| Embedding | mặc định `hash` (`local-hash-embedding-v1`), không gọi Ollama embedding |
| Trần token đầu ra | 700 cho mọi điều kiện (A, B0/B, C, planning, normalization) — đo được 0 lần cắt trong pilot |
| Nhiệt độ | 0,1 (mặc định provider), không đặt seed |
| Hồ sơ | `m0` mặc định sản phẩm không đổi; `IMPLEMENTATION_PROFILE=dev` chỉ trong tiến trình thí nghiệm (cần cho C) |
| Tham số pipeline | `max_context_tokens=3000`, `max_run_tokens=12000`, `task_top_k=6`, `planning_top_k=3`, `retrieval_min_score=0.18`, `retry_limit=1`, context policy `adaptive_qwen` cho C |
| `config_hash` quan sát | C: `b1d69780150d44cc` (pilot C_run1; ghi lại mỗi run, không đổi trong lần chính) |
| Mã | commit G-freeze + code commit ghi trong `meta` của từng run; chạy trên commit đã gắn tag trước khi bắt đầu |
| Điều kiện | A = gọi thẳng, không tài liệu; B0/B = pipeline có nguồn (B0 verdict cũ, B qua luật verdict, cùng một lượt gọi); C = pipeline P/N/O. Memory và Router chưa nối, ngoài phạm vi |
| Dữ liệu | 30 yêu cầu pilot (`pilot_cases.json`) + 10 yêu cầu ghép (`compound_cases.json`) = 40 yêu cầu; nhãn do nhóm gán (kappa tính giữa hai người), AI soạn đề |
| Không thay đổi trong lúc chạy | prompt, luật verdict/slot_check, citation_check (chỉ đo), trần token, model |

## Thứ tự chạy (cố định)
Mỗi lần lặp r = 1..3, theo thứ tự A (40) → B (40, kèm B0) → C (40). Mỗi (điều kiện, yêu cầu) một lần, tuần tự, một inference tại một thời điểm. Máy yên (không full suite, không Ollama khác). Kết quả: `results\main_r<r>\<cond>`. Lỗi một run không dừng cả đợt, trừ khi 3 yêu cầu C đầu tiên đều FAILED.

## Ước lượng (từ số đo pilot)
| Điều kiện | Lượt/yêu cầu | 40 yêu cầu/lần | Giây/yêu cầu | Thời gian/lần |
|---|---|---|---|---|
| A | 1 | 40 | 1,7 | ~1,2 phút |
| B (+B0) | 1 | 40 | 3,2 | ~2,2 phút |
| C | ~3,7 (3 lượt nếu plan hỏng, ~4 nếu một task, nhiều hơn nếu ghép) | ~150–200 | 14,8 | ~10–13 phút |
Tổng một lần lặp: ~230–280 lượt, ~14–17 phút. **Ba lần lặp: ~700–850 lượt, ~45–50 phút** (+ nạp model). Trần đề xuất cho lần chính: 900 lượt / 60 phút (cần Owner nâng trần pilot 160 lượt/40 phút, hiện đã dùng 136).

## Tiêu chí nghiệm thu đề xuất (về vận hành, không về độ đúng)
1. Hoàn tất: ≥95% run mỗi điều kiện không lỗi hạ tầng (không tính PLAN_REJECTED, báo riêng).
2. Cắt token (`done_reason=length`) ≤5% mọi điều kiện.
3. `citation_valid` = 100% trên run có trích dẫn.
4. Thời gian/run: A ≲5 s, B ≲10 s, C ≲30 s (trung vị).
5. PLAN_REJECTED ở C báo tỉ lệ; >20% thì dừng và xem nguyên nhân (đã bổ sung lưu `pipeline_events` để thấy lỗi xác minh plan).
6. Độ ổn định giữa 3 lần lặp: báo số yêu cầu đổi verdict giữa các lần (đếm thô). Độ đúng: ma trận nhầm lẫn, tỉ lệ trả lời thừa/sai/từ chối, so sánh cặp bằng số ca khác nhau (`score_pilot.py`); không p-value.
Kết quả AI soạn đề, bộ nhỏ: chỉ để pilot/sanity, không kết luận tổng quát.

## Điều kiện bắt đầu
Owner duyệt tài liệu này và trần lượt/thời gian; nhóm đã gán nhãn hai bộ; commit được tag; RAM trống ≥3 GB.
