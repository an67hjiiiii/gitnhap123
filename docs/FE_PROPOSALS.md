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
