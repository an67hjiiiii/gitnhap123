# Đề xuất cho FE (chưa làm, cần FE quyết)

| # | Mục | Vấn đề | Đề xuất | Ưu tiên |
|---|---|---|---|---|
| 1 | Chế độ "research" (App.tsx, Inspector.tsx, ChatPanel.tsx) | Còn nhiều chuỗi tiếng Anh (Inspector: "No run selected", "Corpus is empty", "Refresh chunks"...; App.tsx: "Run condition", "Fake wiring"). Một số được chọn theo `researchMode ? EN : VI` nên sửa sẽ chạm cấu trúc. | Gộp hai nhánh thành một chuỗi tiếng Việt hoặc đưa vào file strings/i18n. | Trung bình |
| 2 | Chat: `run_id` có thể là `null` | Với chào hỏi/ngoài phạm vi, `/api/chat` trả `run_id: null` (không có lần chạy). `useResearchApp` và `ChatPanel` giả định có `run_id`. | Chịu được `run_id` null: không hiện nút nguồn, không mở Inspector. | Cao |
| 3 | Chat có tiến trình | `/api/chat/stream` (SSE: status/done/error) đã có nhưng FE vẫn gọi `/api/chat`, người dùng chờ 10-30 giây không thấy gì. | Dùng stream để hiện "Đang tìm tài liệu…" theo `labels.vi.json`. | Cao |
| 4 | Câu trả lời chat mới | Thêm `intent`, `route`, `rewritten_query`, `query_language` trong phản hồi. | Hiển thị chip "Đã chuyển câu hỏi sang tiếng Việt" khi `query_language.translated` là true. | Thấp |
| 5 | Studio workspaces/admin | `/api/studio/workspaces` và `/api/studio/admin/*` trả 503 khi chạy kho file (chỉ chạy với PostgreSQL). | Hiện thông báo "Tính năng cần cơ sở dữ liệu PostgreSQL" thay vì lỗi chung. | Trung bình |
| 6 | Trạng thái tải | Không có skeleton/loading khi gọi review run dài. | Dùng SSE `/api/review/runs/{id}/events` để hiện tiến độ. | Trung bình |
| 7 | Thuật ngữ | "Corpus", "chunk", "run" lẫn với "tài liệu", "đoạn trích", "lần chạy". | Chốt: tài liệu / đoạn trích / lần chạy ở mọi màn. | Thấp |
| 8 | Chuỗi dùng làm khoá | `StatusBadge`/`statusDescriptions` dùng mã trạng thái BE (COMPLETE, NO_EVIDENCE…) làm khoá; đã chỉ đổi giá trị hiển thị. | Giữ khoá; dùng `labels.vi.json` của BE làm nguồn duy nhất. | Thấp |
| 9 | Panel "Theo tác tử" | `Workspace.tsx` (~dòng 277) chỉ hiện nội dung từng tác tử. | Hiện thêm chip số đo lấy từ `task_results[i].metrics`: `input_tokens/output_tokens · latency_ms · valid_citations`. Chỉ đọc trường mới, không đổi logic. |
| 10 | Tiến độ lập chỉ mục | FE chưa biết chỉ mục đang cập nhật. | Khi nhận `intent_routed.path="REINDEXING"` hoặc poll `GET /api/index/status`, hiện thanh tiến độ `done/total` và tự gửi lại câu hỏi khi `status="done"`. |
| 11 | Chip nguồn | Trích dẫn hiện mã chunk; `sources` đã có ở cấp trên của phản hồi. | Chip "tên tệp · mục" từ `sources[i].doc_name`/`section`; bấm mở đoạn trích (`snippet`, đầy đủ qua `/api/sources/...chunk`). `[n]` trong `answer` bấm nhảy tới chip tương ứng. Ẩn hẳn `chunk_id` khỏi người dùng (chỉ dùng làm khoá). |
| 12 | Nhãn không dựa tài liệu | BE bỏ ghi chú trong `answer`, trả `grounding`. | Khi `grounding==="none"` hiện nhãn nhỏ "Trả lời từ kiến thức chung, không dựa trên tài liệu của bạn" cạnh câu trả lời. |
| 13 | Tệp .docx | Người dùng quen tải Word nhưng danh sách tệp hiện tại là `.pdf,.md,.markdown,.sql,.txt`; backend chưa có trình đọc `.docx` ở đây. | Đề xuất thêm `.docx` (cần trình trích xuất phía BE trước); chưa tự thêm. |
| 14 | Nhãn "đã lược câu" | Khi guard bỏ câu không có căn cứ, trạng thái là `PARTIAL` và `task_results[*].missing_information` có dòng "đã bỏ câu không có căn cứ: …". Người dùng chỉ thấy `PARTIAL`, dễ hiểu là câu trả lời thiếu. | Nếu mọi mục `missing_information` đều bắt đầu bằng "đã bỏ câu không có căn cứ", hiện nhãn nhẹ "Đã lược một câu không có trong tài liệu" (màu trung tính, không dùng màu cảnh báo); các `PARTIAL` còn lại giữ nhãn hiện tại. |
