# Thay đổi chữ hiển thị FE

Chỉ đổi nội dung chuỗi hiển thị (không đổi biến, khoá, JSX, logic, style). Phần giao diện Studio vốn đã là tiếng Việt nên không đổi.

| file:dòng | cũ | mới | lý do |
|---|---|---|---|
| frontend/src/components/ChatPanel.tsx:30 | `"Ready for a new question"` | `"Sẵn sàng nhận câu hỏi mới"` | tiếng Việt, ngắn |
| frontend/src/components/ChatPanel.tsx:31 | `"Retrieving evidence and generating an answer"` | `"Đang tìm căn cứ và viết câu trả lời"` | tiếng Việt, động từ rõ |
| frontend/src/components/ChatPanel.tsx:32 | `"Answer ready"` | `"Đã có câu trả lời"` | tiếng Việt |
| frontend/src/components/ChatPanel.tsx:33 | `"Answer needs review"` | `"Câu trả lời cần được xem lại"` | tiếng Việt |
| frontend/src/components/ChatPanel.tsx:34 | `"No validated evidence found"` | `"Chưa tìm thấy căn cứ phù hợp trong tài liệu"` | nói rõ chuyện gì xảy ra |
| frontend/src/components/ChatPanel.tsx:35 | `"Run failed"` | `"Lần chạy không thành công"` | tiếng Việt |
| frontend/src/components/ChatPanel.tsx:66 | `"Run status received"` | `"Đã nhận trạng thái lần chạy"` | tiếng Việt |
| frontend/src/components/ChatPanel.tsx:112 | `["Selected chunks"` | `["Đoạn được chọn"` | thuật ngữ thống nhất: đoạn trích |
| frontend/src/components/ChatPanel.tsx:113 | `["Valid citations"` | `["Trích dẫn hợp lệ"` | tiếng Việt |
| frontend/src/components/ChatPanel.tsx:327 | `<h2>Start with a focused research question.</h2>` | `<h2>Bắt đầu bằng một câu hỏi cụ thể.</h2>` | trạng thái trống gợi ý bước đầu |
| frontend/src/components/StatusBadge.tsx:10 | `CONNECTING: "Connecting"` | `CONNECTING: "Đang kết nối"` | tiếng Việt |
| frontend/src/components/StatusBadge.tsx:11 | `RUNNING: "Running"` | `RUNNING: "Đang chạy"` | tiếng Việt |
| frontend/src/components/StatusBadge.tsx:12 | `EMPTY: "Empty"` | `EMPTY: "Trống"` | tiếng Việt |
| frontend/src/components/StatusBadge.tsx:13 | `COMPLETE: "Complete"` | `COMPLETE: "Hoàn tất"` | tiếng Việt |
| frontend/src/components/StatusBadge.tsx:14 | `PARTIAL: "Partial"` | `PARTIAL: "Một phần"` | tiếng Việt |
| frontend/src/components/StatusBadge.tsx:15 | `NO_EVIDENCE: "No evidence"` | `NO_EVIDENCE: "Thiếu căn cứ"` | tiếng Việt |
| frontend/src/components/StatusBadge.tsx:16 | `FAILED: "Failed"` | `FAILED: "Thất bại"` | tiếng Việt |
| frontend/src/components/StatusBadge.tsx:17 | `OFFLINE: "Offline"` | `OFFLINE: "Mất kết nối"` | tiếng Việt |
| frontend/src/components/Sidebar.tsx:49 | `"New research run"` | `"Lần chạy mới"` | ngắn hơn |
| frontend/src/components/Sidebar.tsx:49 | `"New conversation"` | `"Cuộc trò chuyện mới"` | tiếng Việt |
| frontend/src/components/Sidebar.tsx:53 | `"Run history"` | `"Lịch sử chạy"` | tiếng Việt |
| frontend/src/components/Sidebar.tsx:53 | `"Conversations"` | `"Cuộc trò chuyện"` | tiếng Việt |
| frontend/src/components/Sidebar.tsx:95 | `<small>Current corpus</small>` | `<small>Tài liệu hiện có</small>` | một khái niệm một tên: tài liệu |
| frontend/src/components/Sidebar.tsx:18 | `"Unknown time"` | `"Chưa rõ thời gian"` | tiếng Việt |
| frontend/src/components/ChatComposer.tsx:50 | `<span>Ask against your local research corpus</span>` | `<span>Hỏi dựa trên tài liệu đã tải lên</span>` | tiếng Việt, rõ nghĩa |
| frontend/src/components/ChatComposer.tsx:51 | `Enter to run · Shift + Enter for a new line` | `Enter để gửi · Shift + Enter để xuống dòng` | tiếng Việt |
| frontend/src/App.tsx:301 | `"Restoring your session…"` | `"Đang khôi phục phiên đăng nhập…"` | tiếng Việt |
| frontend/src/App.tsx:301 | `"Sign in to continue"` | `"Đăng nhập để tiếp tục"` | nút/tiêu đề động từ |
| frontend/src/App.tsx:347 | `"Create your account" : "Sign in"` | `"Tạo tài khoản" : "Đăng nhập"` | tiếng Việt |
| frontend/src/components/LoginForm.tsx:90 | `>Email or username<` | `>Email hoặc tên đăng nhập<` | tiếng Việt |
| frontend/src/components/LoginForm.tsx:118 | `"Signing in…" : "Sign in"` | `"Đang đăng nhập…" : "Đăng nhập"` | tiếng Việt |
| frontend/src/components/RegisterForm.tsx:177 | `"Creating account…" : "Create account"` | `"Đang tạo tài khoản…" : "Tạo tài khoản"` | tiếng Việt |

## Áp lại trên FE mới của nhóm (9650134)

32 chỉnh sửa ở trên vẫn còn nguyên: các file đó không nằm trong 2 commit mới của nhóm. Các trang nhóm vừa đổi (Landing, Login, Register, ForgotPassword, auth/*, PaperStory) đã là tiếng Việt tự nhiên nên không thêm chỉnh sửa nào.
