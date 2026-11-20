# Tích hợp phần C1SE.27 vào CAP1

Nhánh: `tich-hop/studio-c1se27`. Nguyên tắc: **giữ CAP1 làm lõi**. Mọi phần mới đều thêm vào, mặc định không đổi hành vi cũ. Phần nào backend CAP1 chưa có thì giao diện báo rõ, không giả lập.

## Có gì mới

### Backend (`backend/app`)

| Phần | File | Bật bằng | Mặc định |
|---|---|---|---|
| Lưu vết nguồn gốc mỗi lượt chạy (mã băm mã nguồn, thư viện, model digest Ollama, tokenizer, cách embed) | `research/provenance.py`, khóa `provenance` trong bản ghi run | luôn bật | bật |
| Embedding ngữ nghĩa qua Ollama (`nomic-embed-text`, 768 chiều) | `retrieval/embeddings.py` (`OllamaEmbedder`, `make_embedder`) | `EMBEDDING_BACKEND=ollama` | `hash` (như cũ) |
| Chọn evidence theo token Qwen3 thật và chia ngân sách thích ứng giữa các task (chỉ khi cờ O bật: C, C-P, C-N) | `research/token_budget.py`, `research/adaptive_budget.py`, `research/token_context.py` | `CONTEXT_POLICY=adaptive_qwen` | `char_proxy` (như cũ) |
| API cho giao diện Studio | `api/studio.py` (gắn ở cuối `main.py`) | luôn bật | — |

API mới, đều cần đăng nhập:

- `POST /api/studio/retrieval-test`: thử truy xuất, không gọi LLM.
- `POST /api/studio/compare`: chạy cùng một yêu cầu dưới nhiều điều kiện (`A, B, C, C-P, C-N, C-O`).
- `DELETE /api/studio/sources/{id}`: xóa tài liệu **của chính người dùng** (nguồn, đoạn theo CASCADE, vector dẫn xuất).
- `GET /api/studio/admin/overview | table/{name} | security-audit | db-diagnostic`: chỉ ADMIN. Trang xem bảng **không bao giờ trả** `password_hash` hay `token_hash`.

Lưu ý khi đổi `EMBEDDING_BACKEND`: phải dùng `VECTOR_COLLECTION` mới (ví dụ `domain_nomic`) hoặc index lại. Không trộn vector hash với vector ngữ nghĩa.

Phụ thuộc mới: `tokenizers==0.22.2`. Tokenizer Qwen3 offline nằm ở `backend/app/assets/qwen3/`, đã pin SHA-256, kèm giấy phép.

### Thực nghiệm (`data/research`, `scripts/research`)

- `data/research/dev-v1/cases.json`: 20 tình huống dev. SHA-256 ghi trong README. Đây là dữ liệu dev, **không phải held-out**.
- `scripts/research/run_conditions.py`: chạy bộ dữ liệu dưới nhiều điều kiện, lặp N lần, ghi `results.jsonl` kèm số đo thật và lưu vết. Tài khoản đọc từ `RUNNER_EMAIL` / `RUNNER_PASSWORD`, không ghi vào file.
- `scripts/research/verify_results.py`: kiểm tra đủ lượt, không trùng, mã nguồn và model nhất quán; in trung vị theo điều kiện. Số mô tả kỹ thuật, không chấm chất lượng.

### Frontend (`frontend/src`)

- `/`: trang giới thiệu, Robot C27. Nội dung đã đồng bộ với CAP1: 8 bước đúng pipeline (giống màn hình 8 bước trong Studio), ba tác tử Security / Database / API-Architecture Analyst, các điều kiện so sánh A, B, C (đúng ba cách trả lời trong Studio), PostgreSQL thay SQLite; bỏ "Shared Brief" (CAP1 không có) và dải số 3/8/4 ở trang đầu.
- `/login`, `/register`: dùng phiên cookie của CAP1.
- `/studio`: **không gian làm việc thống nhất** (một trang thay cho Điều phối + Trò chuyện riêng):
  - màn hình đầu: Robot C27 lớn với bong bóng lời thoại (chữ hiện dần), tình trạng kho (tên không gian, số tài liệu và đoạn của không gian đó, mô hình), khung chat bấm vào thì phóng to dần (khoảng 0,6 giây) và hiện 6 câu hỏi phổ biến (tóm tắt, quy trình, điều kiện, người phê duyệt, thuật ngữ, rủi ro), dải tài liệu của không gian (bấm để hỏi về tài liệu đó), 3 cuộc trò chuyện gần nhất; kho trống thì có nút dùng bộ mẫu;
  - mỗi lần chạm Robot đổi một trong 5 biểu cảm nhẹ cùng kiểu mắt gốc (mỉm cười, tò mò, ngạc nhiên nhẹ, hài lòng, nháy mắt); biểu cảm khi đọc tài liệu, làm việc giữ nguyên kèm một câu nói;
  - trong cùng một cuộc trò chuyện có thể **Hỏi nhanh** (chế độ sản phẩm CAP1, nhớ ngữ cảnh) hoặc **Phân tích** (điều kiện A/B/C);
  - mỗi câu trả lời có trạng thái bằng chứng, nút nguồn (xem đoạn tài liệu), **8 bước** (sự kiện thật của CAP1) và **Theo tác tử**;
  - thanh bên: kho tài liệu (tải lên, xem đoạn, thử truy xuất, **xóa**) và danh sách **cuộc trò chuyện** (một lịch sử chung, không trùng lặp).
- **Không gian làm việc** (bảng `studio_workspaces`, `studio_workspace_items`, migration `20261111_04`): tạo, chuyển và xóa trong menu tên không gian ở thanh bên. Mỗi không gian có tài liệu và cuộc trò chuyện riêng; câu hỏi chỉ truy xuất trong tài liệu của không gian đang mở (gửi `source_ids`). Xóa không gian: chọn chuyển tài liệu sang không gian còn lại hoặc xóa luôn; không xóa được không gian cuối cùng.
- Thực nghiệm (so sánh A/B/C, cấu hình chỉ đọc, nhật ký) và Cơ sở dữ liệu (chỉ ADMIN).
- `/chat`: **giao diện trò chuyện gốc của CAP1, giữ nguyên**.
- Hai giao diện nạp CSS riêng (`ChatRoute.tsx`, `studio/StudioRoot.tsx`) nên không ảnh hưởng nhau.
- Mã Studio nằm trong `frontend/src/studio`. Lớp `studio/services/api.ts` gọi API CAP1. `studio/services/adapt.ts` chuyển bản ghi run của CAP1 sang dạng màn hình Studio dùng.
- Ánh xạ cách làm: Vanilla = A, Multi-Agent cơ bản = B, Điều phối đầy đủ = C.
- Thêm phụ thuộc: `react-router-dom`, `lucide-react`, `gsap`, `@gsap/react`, `@fontsource/be-vietnam-pro` (chỉ nạp nét 800/900 cho tiêu đề landing).
- Tiêu đề landing: Be Vietnam Pro 900; từ khóa màu xanh; vệt highlight chỉ ở 3 phần: 4 chương câu chuyện, "Mỗi tác tử, một góc nhìn", "Hiệu quả cần được đo". Trước đây từ khóa khai báo Playfair Display nhưng font này chưa từng được nạp nên hiện thành Times New Roman nghiêng.

## Chạy thử

Cách đơn giản: xem `docs/HUONG_DAN_CHAY_DU_AN.md` (cài một lần, sau đó Ctrl+Shift+B trong VS Code chạy Ollama, backend, frontend). Chạy tay:

```powershell
# backend (PostgreSQL theo docker/docker-compose.yml, Ollama có qwen3:4b và nomic-embed-text)
$env:DATABASE_URL="postgresql+psycopg://cap1_ai:<mật-khẩu>@127.0.0.1:55435/cap1_ai_midterm_multilingual"
$env:PROVIDER="ollama"; $env:IMPLEMENTATION_PROFILE="m2"
$env:VECTOR_INDEX_BACKEND="qdrant"; $env:VECTOR_INDEX_PATH="<thư mục qdrant>"
$env:EMBEDDING_BACKEND="ollama"; $env:VECTOR_COLLECTION="domain_nomic"; $env:CONTEXT_POLICY="adaptive_qwen"
cd backend; .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend (API_TARGET mặc định http://127.0.0.1:8000)
cd frontend; npm run dev -- --host 127.0.0.1
```

## Đã kiểm tra (11/11/2026)

- Backend: `pytest` có 18 ca đạt. Gồm 4 ca gốc, 9 ca cho ngân sách, tokenizer, embedder và lưu vết, 5 ca cho API Studio.
- Frontend: `tsc -b` và `npm run build` đạt.
- Chạy thật với PostgreSQL 16 (Docker), Ollama qwen3:4b, nomic-embed-text:
  - Bộ chạy 6 lượt (D01–D03 × A, C) đạt kiểm tra cấu trúc. Lưu vết có model digest và context policy trong bảng `runs`.
  - So sánh A, B, C, C-O chạy được. Chỉ C có bước `adaptive_budget_plan`.
  - API quản trị: tài khoản thường nhận 403, không lộ cột mật khẩu.
- Không gian làm việc (Playwright, 1440 px): tạo không gian mới thì thấy 0 tài liệu, xóa thì quay về Kho chính với 3 tài liệu; 5 lần chạm Robot cho 5 câu nói khác nhau; màn hình đầu ở 390 px không tràn ngang.
- Trình duyệt (Playwright, 1440 và 390 px): trang chủ, đăng nhập, Studio, xem mẩu, thử truy xuất, mở lại lịch sử, 8 bước, chạy điều kiện A, thực nghiệm, quản trị, và trang `/chat` gốc. Không lỗi mạng ngoài 401 kiểm tra phiên trước khi đăng nhập, không tràn ngang.

## Phân quyền

CAP1 có hai vai trò hệ thống: USER và ADMIN. Mỗi người chỉ thấy và xóa được tài liệu, cuộc trò chuyện, lượt chạy của chính mình (máy chủ kiểm tra). ADMIN thấy thêm trang Cơ sở dữ liệu; các API `/api/studio/admin/*` trả 403 với USER. Bốn vai trò cũ của C1SE.27 (developer, tech_lead, researcher, admin) không mang sang.

### Không gian tổ chức và phân quyền theo cấp bậc (16/11/2026)

Thêm lớp thứ hai, độc lập với USER/ADMIN: **cấp bậc trong từng không gian tổ chức** (Nhân viên, Trưởng phòng, Ban giám đốc, cờ Chủ không gian). Một tài khoản có thể ở nhiều tổ chức với cấp bậc khác nhau. Không gian cá nhân (Kho chính, các thư mục) giữ nguyên hành vi cũ.

**Mức mật tài liệu** (thang thấp đến cao; Riêng tư nằm ngoài thang):

| Mức | Ai xem | Ai đặt được |
|---|---|---|
| Riêng tư | Người tải lên (khi rời tổ chức thì bàn giao cho Trưởng phòng hoặc Ban giám đốc) | Mọi cấp |
| Toàn công ty | Mọi thành viên | Trưởng phòng trở lên |
| Nội bộ phòng | Thành viên phòng đó và Ban giám đốc | Mọi cấp |
| Hạn chế | Trưởng phòng của phòng đó và Ban giám đốc | Mọi cấp (nhân viên nộp báo cáo lên trên) |
| Mật | Ban giám đốc | Ban giám đốc |

Ngoài ra có chia sẻ trực tiếp cho một người hoặc một phòng. Người tải lên chỉ được tăng mức; hạ mức là việc của Trưởng phòng (trong phòng mình) hoặc Ban giám đốc. Bảng đầy đủ quyền mời, duyệt, gỡ, sửa thành viên nằm ở `backend/app/core/access.py`.

**Kiến trúc**

- Luật nằm ở **một module duy nhất** `backend/app/core/access.py`; API và luồng AI đều gọi module này. Nguyên tắc đóng khi nghi ngờ: thành viên chờ duyệt, mức mật lạ, thiếu dữ liệu đều coi là không có quyền.
- Phạm vi của yêu cầu là tham số `?space_id=` (frontend tự gắn khi đang mở một tổ chức). `current_principal` trong `main.py` kiểm tra thành viên đang hoạt động (403 nếu không) rồi mọi kho (tài liệu, lượt chạy, hội thoại) đọc phạm vi từ đó.
- **AI chỉ nhìn thấy tài liệu được phép**: kho tài liệu theo phạm vi là cửa duy nhất đưa đoạn văn vào pipeline, cả đường vector (Qdrant lọc theo danh sách tài liệu được phép) lẫn đường từ khóa dự phòng. Danh sách rỗng nghĩa là không tìm gì; bộ lọc vector từ chối mọi lượt tìm không có phạm vi. Câu trả lời không nhắc tới sự tồn tại của tài liệu cấm.
- Lượt chạy và hội thoại mang phạm vi (`runs.space_id`, `conversations.space_id`). Câu trả lời cũ bị ẩn ("Nội dung đã ẩn do thay đổi quyền truy cập") khi người xem không còn quyền với mọi tài liệu nó dùng (bị hạ cấp, chuyển phòng, bị gỡ).
- ADMIN hệ thống không đọc nội dung tổ chức qua ứng dụng: trang Cơ sở dữ liệu, phản hồi, nhật ký hoạt động che tên tài liệu, câu hỏi, tiêu đề hội thoại của tổ chức.
- Thông báo tài liệu: khi một tài liệu được nộp vào tổ chức hoặc đổi mức mật, chỉ những người **vừa được quyền xem** nhận thông báo (tính bằng cùng luật `can_view`, gồm cả chia sẻ trực tiếp); người đã xem từ trước và người không có quyền không được báo, nên thông báo không làm lộ sự tồn tại của tài liệu cấm. Bảng tài liệu ở trang Tổ chức ghi người tải lên và ngày tải.
- Báo cáo đã lưu và Chấm mù chỉ dùng trong không gian cá nhân (người chấm nhận câu trả lời qua mã nên không được mang nội dung tổ chức ra ngoài).
- Điều kiện nghiên cứu A/B/C, planner, bước kiểm tra kế hoạch không đổi; phân quyền chỉ là lớp lọc đứng trước truy xuất. Dữ liệu cũ (39 tài liệu, 61 hội thoại, 374 lượt chạy lúc chuyển đổi) đều thuộc phạm vi cá nhân nên kết quả cũ không đổi.

**Mã nguồn**: CSDL `models.py` + migration `20261115_08_org_access` và `20261116_09_run_space`; luật `core/access.py`; API `api/org.py` (`/api/org/*`: không gian, phòng ban, thành viên, lời mời theo email/link/mã có hạn dùng và lưu dạng băm, duyệt, bàn giao, nộp tài liệu, đổi mức mật, chia sẻ, thông báo); kho theo phạm vi `storage/postgres/runtime.py`; frontend `components/OrgView.tsx`, `styles/org.css`, chuông thông báo trong `Header.tsx`, chọn mức mật trước khi tải trong `LeftPanel.tsx`, gắn phạm vi tự động trong `services/api.ts`.

**Kiểm tra**: 75 ca kiểm thử mới (`test_org_schema`, `test_access_policy`, `test_access_retrieval` gồm test rò rỉ 7 người × 6 câu trên cả đường vector và từ khóa có đối chứng, `test_access_api`, `test_org_api`); đã thử cố ý làm yếu bộ lọc để xác nhận test bắt được. Trình duyệt (16/11, 3 tài khoản thử, Ollama thật): tạo công ty, mời qua chuông, vào bằng mã chờ duyệt, tải tài liệu Mật; cùng câu hỏi về tài liệu Mật thì Trưởng phòng nhận "không có thông tin", Ban giám đốc nhận câu trả lời có trích dẫn; đổi mức mật làm nhân viên mất quyền ngay; chia sẻ có thông báo; gỡ thành viên; giao diện điện thoại 375 px không tràn ngang; chế độ tối.

**Giới hạn**: chặn ở tầng ứng dụng, người quản trị máy chủ vẫn đọc được CSDL trực tiếp; danh sách tài liệu được phép tính bằng cách nạp mọi tài liệu của không gian (đủ cho vài nghìn tài liệu); bộ đếm đoán mã sai nằm trong bộ nhớ (về 0 khi khởi động lại); mỗi người thuộc một phòng trong một không gian; chưa có duyệt tài liệu nhiều cấp, chia sẻ có thời hạn, gửi email thật.

## Hiệu năng trang giới thiệu

Các giá trị đổi theo cuộn (chương câu chuyện, bước đường ray) và hộp phương pháp tự chuyển được tách thành khối nhỏ, nên không render lại cả trang. Đo bằng Playwright (cuộn hết trang): trước 10 long task, khoảng 1 giây; sau 0 long task, ngang bản C1SE.27 gốc. Hiệu ứng, mốc cuộn và âm thanh giữ nguyên.

## Chức năng phân tích (13/11/2026)

Module riêng `backend/app/analysis/` và API `backend/app/api/analysis.py` (`/api/studio/...`), không đi qua `/api/chat`, planner hay bước kiểm tra kế hoạch của CAP1; luồng nghiên cứu A/B/C giữ nguyên. Báo cáo lưu trong bảng mới `studio_reports` (migration `20261113_05`, tạo tự động khi backend khởi động). Giao diện: các mục mới ở thanh bên của Studio. Cách dùng: `docs/HUONG_DAN_SU_DUNG.md`.

| Chức năng | Mã nguồn | Ghi chú phương pháp |
|---|---|---|
| Truy vết yêu cầu | `analysis/traceability.py`, `components/ChecklistView.tsx` | Trích yêu cầu có mã (không dùng mô hình); tác tử chọn theo chuyên môn; kết luận có lược đồ JSON và kiểm tra trích dẫn; quy tắc hạ kết luận (không căn cứ, còn điểm thiếu, thiếu con số mục tiêu) |
| Gói thiết kế kỹ thuật | `analysis/design.py`, `components/DesignView.tsx` | Ý chính → ba tác tử → kiểm tra độ phủ; mỗi tác tử truy xuất riêng, ưu tiên đoạn tác tử trước chưa dùng; đo token và thời gian theo từng tác tử; sinh SQL/OpenAPI nháp |
| Rà soát bảo mật | `analysis/security_review.py` | 32 tiêu chí chọn lọc OWASP ASVS 4.0.3, tác tử Bảo mật, thêm quy tắc thuật ngữ cốt lõi phải có trong đoạn trích |
| Kiểm tra mâu thuẫn | `analysis/consistency.py`, `components/ConsistencyView.tsx` | Ghép cặp câu quy định cùng chủ đề khác con số/phủ định (không dùng mô hình); chỉ tự xác nhận xung đột con số cùng phạm vi |
| Kiểm chứng câu trả lời | `analysis/grounding.py`, `components/AnswerTools.tsx` | Đối chiếu từng câu với đoạn lượt chạy đã đọc (trùng từ 0,7 + trùng cặp từ 0,3; con số phải có trong đoạn); không gọi mô hình, không đổi lượt chạy |
| Hồ sơ tài liệu | `analysis/insights.py`, `components/DocumentProfileView.tsx` | Tại máy: chất lượng, thông tin nhạy cảm (chỉ trả giá trị đã che, thẻ qua Luhn), thuật ngữ định nghĩa sẵn, tài liệu liên quan (cosine), so dòng hai phiên bản. Mô hình: tóm tắt, câu hỏi gợi ý (mã đoạn ràng buộc enum), định nghĩa thuật ngữ, tóm tắt thay đổi |
| Đọc tài liệu, sơ đồ tư duy, báo cáo | `analysis/reading.py`, `components/DocumentReader.tsx`, `components/MindMap.tsx`, `components/analysis/exporters.tsx` | Sơ đồ theo đề mục (tại máy) hoặc do mô hình gom ý (mã đoạn rút gọn D1, D2… ràng buộc enum rồi đổi lại mã thật); giải thích đoạn bôi đen; báo cáo từ câu trả lời (nguồn lấy từ đoạn thật, không do mô hình viết); Word dựng bằng thư viện chuẩn `zipfile`; PDF qua hộp thoại in |
| Neo nghĩa vụ khi kiểm tra kế hoạch | `research/plan_anchoring.py`, gọi trong `research/pipeline.py` | Chỉ chạy sau khi lần sửa bằng mô hình vẫn bị từ chối: chép nguyên văn nghĩa vụ/mối quan tâm vào nhiệm vụ đã nhận; nếu nhiệm vụ nhận sai mảng theo luật định tuyến của bộ kiểm tra thì chuyển sang đúng tác tử. Kế hoạch vẫn phải qua đúng `verify_task_plan` cũ; ghi sự kiện `plan_anchoring` (thay đổi, lỗi, nhiệm vụ) |
| Nhiệm vụ phụ thuộc | `research/worker.py`, `research/pipeline.py` | Tác tử của nhiệm vụ phụ thuộc nhận kết quả các nhiệm vụ tiền đề trong khối `[UPSTREAM]` (để nhất quán, không phải bằng chứng, không được trích dẫn) |
| Đo tài nguyên | `core/telemetry.py`, `RunMetrics` | Thêm `cpu_percent` (CPU toàn máy trung bình trong lượt) và `model_rss_mb` (RAM tiến trình Ollama) |
| Chấm mù | `analysis/blind_rating.py`, API `/api/studio/rating/*`, migration `20261114_07`, `components/BlindRatingView.tsx` | Mục chấm giữ điều kiện ở máy chủ, xáo thứ tự theo người chấm, chặn chủ đợt tự chấm; Krippendorff alpha khoảng, Wilcoxon cặp |
| Câu hỏi tiếp nối | `research/conversation_context.py` (`resolve_follow_up`), `research/pipeline.py` | Chỉ ở chế độ sản phẩm (`product_mode`): câu ngắn hoặc có từ chỉ trỏ được ghép câu hỏi trước vào truy vấn truy xuất và câu hỏi gửi mô hình; ghi sự kiện `follow_up_resolved`. Điều kiện A/B/C của thực nghiệm không đổi |
| Kiểm tra kho, thống kê, phản hồi cho quản trị | `analysis/reading.py` (`library_quality`, `question_topics`), `GET /api/studio/admin/feedback`, `components/AdminFeedbackModal.tsx` | Trùng tài liệu theo cosine ≥ 0,9; chủ đề tách từ ghép theo tần suất cặp chữ trong kho; phản hồi cho quản trị chỉ ADMIN xem |
| Phản hồi, nhật ký, tổng quan | `api/analysis.py`, middleware trong `main.py`, `components/OverviewView.tsx` | Bảng `studio_feedback`, `studio_activity` (migration `20261113_06`); nhật ký ghi tên thao tác và đối tượng, không ghi nội dung; ghi lỗi không làm hỏng yêu cầu |
| Phòng đánh giá | `analysis/evaluation.py`, `components/EvaluationView.tsx` | Bộ câu hỏi có ý chính, chạy A/B/C (cùng thiết lập ngôn ngữ cho mọi điều kiện), chấm mù, Wilcoxon cặp chính xác (đối chiếu ví dụ chuẩn của R), khoảng tin cậy 95%, rank-biserial, Cohen's dz |

Truy xuất bằng chứng của module này dùng BM25 (cặp âm tiết) trước, thiếu mới bù vector: trên 12 câu có đáp án của bộ tài liệu mẫu, đoạn đúng vào top 4 ở 12/12 câu, so với 6/12 khi chỉ dùng vector nomic (kiểm tra kỹ thuật, không phải số liệu nghiên cứu). Truy xuất của A/B/C không đổi.

## Đa ngành: lĩnh vực của không gian (18/11/2026)

Trước đây planner chỉ có 3 tác tử phần mềm (Security, Database, API/Architecture). Chạy thử với tài liệu Giáo dục và Nhân sự (smoke test 12 lượt, tài liệu mẫu tự viết): A và Hỏi nhanh trả lời đúng; B và C cả 6 lượt "không có bằng chứng" vì giao "nghỉ phép" cho Security, "tiền làm thêm" cho Database và dịch từ khóa tìm kiếm sang tiếng Anh.

**Bộ lĩnh vực** (`backend/app/research/registry.py`, `PACKS`): mỗi bộ gồm tác tử (tên, phạm vi, năng lực, loại trừ), từ khóa nhận diện, mẫu lập kế hoạch.

| Bộ | Tác tử |
|---|---|
| `software` (Phần mềm) | security, database, api_architecture: **giữ nguyên từng ký tự prompt, từ khóa, mẫu của CAP1** |
| `general` (Tổng quát) | general |
| `education` (Giáo dục) | general, academic_affairs, student_affairs, faculty_research |
| `legal_admin` (Hành chính – Pháp lý) | general, legal_basis, procedure, contract |
| `business_hr` (Doanh nghiệp – Nhân sự) | general, hr_policy, operations, sales_customer |

- Bộ đang dùng đặt theo từng lượt: `pipeline.run(..., domain_pack=...)` (ContextVar); decomposer, trích nghĩa vụ, kiểm tra kế hoạch, worker, mẫu lập kế hoạch đọc bộ đang dùng. Lượt chạy ghi `effective_config.domain_pack`.
- **Không truyền = `software`**: trang Thực nghiệm, Phòng đánh giá, `/api/studio/compare` và `scripts/research/*` không gửi trường này nên điều kiện A/B/C chạy đúng như trước (test `test_software_is_default_and_prompts_unchanged`).
- Bộ ngoài Phần mềm thêm: tác tử `general` cho câu ngoài phạm vi; quy tắc giữ goal, evidence_needs, mô tả nghĩa vụ bằng ngôn ngữ của yêu cầu; khi từ khóa ngành rõ ràng mà mô hình gán sai miền cho một mối quan tâm thì sửa nhãn thay vì hủy lượt (bộ Phần mềm vẫn hủy như cũ). Từ khóa tiếng Việt của mẫu lập kế hoạch chỉ dùng chấm điểm, không đưa vào prompt.
- Lưu trữ: cột `domain_pack` ở `studio_workspaces` và `org_spaces` (migration `20261118_14`, sau `20261118_13`). Dòng cũ = `software`; không gian mới mặc định `general`; tổ chức mới gợi ý theo mẫu (Trường học → Giáo dục, Cơ quan → Hành chính – Pháp lý, Doanh nghiệp → Doanh nghiệp – Nhân sự). Giá trị kiểm ở API, không đặt CHECK.
- Giao diện: chọn lĩnh vực khi tạo không gian và đổi trong menu không gian; câu hỏi trong không gian gửi kèm `domain_pack`. Ba công cụ chỉ dành cho Phần mềm (Chất lượng yêu cầu, Gói thiết kế, Rà soát bảo mật) gom vào nhóm "Bộ công cụ Phần mềm", chỉ hiện khi không gian là Phần mềm; "Truy vết yêu cầu" đổi tên "Đối chiếu yêu cầu"; bộ lọc Dữ liệu/API/Bảo mật ở kho tài liệu chỉ hiện ở Phần mềm.
- Tải lên **Word (.docx) và Excel (.xlsx)**: đọc bằng thư viện chuẩn Python (zip + XML), không thêm phụ thuộc; tiêu đề Word thành dòng `#`, bảng và hàng Excel thành dòng `ô | ô`; chặn tệp hỏng và tệp nén bom (giới hạn 40 MB sau giải nén). Chưa đọc .doc/.xls cũ, chưa OCR.
- Kiểm tra: `test_domain_packs.py`, `test_office_ingestion.py`. Chạy lại smoke test với bộ Giáo dục / Nhân sự: B và C giao đúng tác tử ngành, giữ tiếng Việt, cả 6 lượt có câu trả lời dựa trên tài liệu (đa số trạng thái "một phần"). Đây là kiểm tra kỹ thuật, chưa phải số liệu chất lượng.
- **Bộ công cụ theo ngành (19/11)**: thanh bên có một mục "Bộ công cụ <ngành>" (`components/ToolkitView.tsx`). Trang đầu là các thẻ công cụ mang màu của ngành; bấm thẻ mở công cụ, có thanh chuyển nhanh giữa các công cụ cùng ngành. Mỗi ngành sở hữu bộ công cụ riêng theo nghiệp vụ:

  | Ngành | Công cụ (thư mục `components/tools/`) | Cách làm |
  |---|---|---|
  | Giáo dục | Xét duyệt theo danh sách | Ngưỡng lấy từ quy chế (có trích dẫn, sửa được) → tải bảng điểm .xlsx/.csv → gán cột → so sánh từng hàng bằng mã cố định: Đạt / Không đạt / Thiếu số liệu |
  | | Tạo câu hỏi ôn tập | Trắc nghiệm 4 phương án, sinh theo lượt 5 câu; bỏ câu có đáp án không nằm trong đoạn trích |
  | | Tra cứu quy chế theo Điều | Cắt văn bản theo "Điều N" (không dùng mô hình); hỏi đáp chọn Điều bằng BM25, Điều được dẫn phải nằm trong danh sách đã tìm |
  | Doanh nghiệp – Nhân sự | Tính phép năm, tiền làm thêm | 7 hệ số lấy từ nội quy (có trích dẫn) → công thức cố định; thiếu hệ số thì để trống kèm lý do |
  | | Duyệt đơn từ | Kiểm điều kiện (bộ máy Kiểm tra điều kiện) + cấp duyệt (tên người duyệt phải có nguyên cụm trong nội quy; hỏi lại một lần nếu trả rỗng) |
  | | Hỏi đáp chính sách | Bộ câu hỏi thường gặp; bỏ câu trả lời có con số không có trong đoạn trích |
  | Hành chính – Pháp lý | Rà soát hợp đồng | 7 nội dung theo Điều 398 BLDS 2015 + 2 mục thực hành; nội dung không có chữ nào trong nhóm từ của nó → "Chưa thấy"; điều khoản rủi ro phải có nguyên văn trong hợp đồng |
  | | Hồ sơ thủ tục | Giấy tờ cần nộp (đánh dấu đã có → còn thiếu), các bước, thời hạn, lệ phí (con số phải có trong đoạn trích) |
  | | Hiệu lực văn bản | Không dùng mô hình: số hiệu (ưu tiên dòng "Số: …"), ngày ban hành, "có hiệu lực từ ngày…", "thay thế/bãi bỏ…". Chỉ coi là bị thay thế khi văn bản thay thế đã đến ngày hiệu lực; "bãi bỏ Điều 5 của…", "sửa đổi, bổ sung…" là sửa một phần, văn bản gốc vẫn còn hiệu lực |
  | Phần mềm | Rà soát theo tiêu chí · Chất lượng yêu cầu · Gói thiết kế | Giữ bộ cũ; "Truy vết yêu cầu" + "Rà soát bảo mật" gộp thành Rà soát theo tiêu chí (nguồn: yêu cầu có mã / OWASP ASVS / danh mục tự nhập) |
  | Tổng quát | Quy trình từng bước · Kiểm tra điều kiện · Rà soát theo tiêu chí | Công cụ chung cho mọi loại quy định |

  Hồ sơ tài liệu, Kiểm tra mâu thuẫn giữ ở thanh bên cho mọi ngành; Phòng đánh giá chuyển vào nhóm Nghiên cứu. Câu lệnh của công cụ chung bỏ giả định "software project / engineer".
  - API: `analysis/domain_tools.py` và `analysis/casework.py`, đường dẫn `/api/studio/tools/*` (table, thresholds, roster/evaluate, generate, articles, lookup, pay-rates, pay-compute, approver, contract-criteria, contract-risks, validity) và `/api/studio/casework/{conditions,procedure}`.
  - Luật chung khi chạy thật với qwen3:4b: mô hình hay dẫn nhầm đoạn bên cạnh → tự chuyển trích dẫn sang đoạn chứa đúng con số; hay chép dữ kiện tình huống thành "điều kiện" → loại và hỏi lại một lần; hay trả rỗng → hỏi lại một lần; số thứ tự "Điều 10", "Mục 8", "2." không tính là con số của quy định; ô "Không có thông tin…" coi như trống; danh sách dài sinh theo lượt để JSON không bị cắt.
  - Kiểm tra: `test_casework.py`, `test_domain_tools.py` (luật nghiệp vụ, kể cả các lỗi gặp khi chạy thật). Chạy thật trên tài liệu mẫu tự viết: 9/9 công cụ cho kết quả đúng kỳ vọng ở lần chạy cuối; đây là kiểm tra kỹ thuật, chưa phải đánh giá chất lượng.
- Để sau: bộ Y tế, Tài chính (cần chuyên gia kiểm tra); cắt tài liệu theo Điều/Khoản; đo rồi mới cân nhắc đổi embedding (bge-m3); bộ câu hỏi đánh giá đa ngành và chấm mù; viết lại trang giới thiệu.

## Lộ trình hệ thống đích, theo đợt (19/11/2026)

Theo mục 12 tài liệu `MO_TA_HE_THONG_DICH_VA_QUY_TRINH_NGUOI_DUNG_2026-11-19.docx`. Việc 0: đã commit phần đa ngành và phần tổ chức (`9faaf3e`, chỉ trên máy).

### Đợt 1: câu trả lời nhiều ý không bị cắt

- Nguyên nhân gốc: prompt SYNTHESIZER có chữ "validated by workers", trùng dấu hiệu `WORKER` trong `providers/ollama.py`, nên bước tổng hợp bị ép ra JSON tự do; câu trả lời dài chạm giới hạn 700 token thì JSON bị cắt giữa chừng (có từ code gốc CAP1).
- Sửa, chỉ cho ô chat sản phẩm (`product_mode`): bước tổng hợp dùng khuôn JSON chỉ một trường `answer`, giới hạn riêng `SYNTHESIS_MAX_OUTPUT_TOKENS` (mặc định 1800, ghi vào `effective_config`), rồi lấy trường `answer`. Không có khuôn thì qwen3:4b viết cả phần suy nghĩ bằng tiếng Anh vào câu trả lời, nên không bỏ JSON được.
- Thực nghiệm A/B/C không đổi: vẫn đi nhánh cũ (ép JSON tự do, 700 token) để tái lập kết quả đã có. Có nên sửa cả nhánh thực nghiệm hay không là việc của nhóm, vì nó thay đổi đầu ra của B/C.
- Kiểm tra: `test_synthesis_limit.py` (5 kiểm thử). Toàn bộ backend: 290 đạt. Chạy thật với qwen3:4b, điều kiện C, câu "trình bày đầy đủ ba ý" trên nội quy mẫu: đủ 3 ý, có nguồn, 30 giây, 1464 token đầu ra cho cả lượt. Trước khi sửa, cùng câu này cho ra JSON chép lại đầu vào.

### Đợt 2a: lỗi hiển thị nhỏ

- Màn hình mở đầu chỉ chạy lần đầu trong phiên trình duyệt (`sessionStorage`), tải lại trang không chạy lại.
- Tên nguồn không lặp: hàm đổi mã đoạn thành nhãn tách ra `utils/citations.ts`. Mô hình viết "noi-quy-mau.txt [src_…]" thì chỉ hiện "(đoạn 1)"; một đoạn dẫn hai lần liền thì hiện một nhãn. Kiểm thử `frontend/tests/citations.test.mjs` (`npm test`, 4 đạt).
- Robot không che nút: trên máy tính, bản đồ chỗ trống của robot nới nút, ô nhập thêm nửa ô mỗi phía và cho nặng gấp 10 lần ô chữ; robot tính theo cả khung nhận cú bấm 64 px; che một ô nút là đủ làm robot dời chỗ. Trước khi sửa, trang Hồ sơ tài liệu bị robot đè nút "Kiểm tra cả kho". Kiểm tra trên trình duyệt 1024 px với bản sửa cuối: 6 trang (Hồ sơ tài liệu, Kiểm tra mâu thuẫn, Bộ công cụ, Tổng quan, Tổ chức, Thực nghiệm) không còn nút nào bị chồng. Trên điện thoại robot đậu ở thanh trên cùng, không chồng nút.
- Nút trên điện thoại (dưới 768 px) có vùng bấm tối thiểu 44 px; nút đóng thanh bên chuyển ra cuối hàng để không đè chữ logo. Đo trên khổ 375 px: chỉ còn ô tìm tài liệu cao 20 px nằm trong khung 32 px.
- `npx tsc -b` và `npm run build` đạt.

### Đợt 2b: hiện chữ dần và tiến trình từng bước

- Backend: `POST /api/chat/stream` (chỉ cho `product_mode`) chạy đúng luồng `/api/chat` nhưng trả từng dòng JSON: `progress` (tên bước và mã nhiệm vụ, không có nội dung), `answer` (chữ trả lời đang viết), rồi `done` (kèm lượt chạy) hoặc `error`. Tiến trình đi qua ContextVar `research/progress.py`; không có người nghe thì pipeline, `/api/chat` và thực nghiệm không đổi. Ollama trả chữ theo luồng (`stream=True`) chỉ khi có người nghe, ở bước tổng hợp (nhánh sản phẩm) và bước trả lời thẳng. Người dùng đóng trang giữa chừng thì lượt chạy vẫn chạy xong và được lưu.
- Frontend: ô chat hiện bước đang làm, các bước đã qua và chữ trả lời hiện dần (`utils/progress.ts`, kiểm thử `tests/progress.test.mjs`). Backend cũ chưa có stream (404) thì quay về `/api/chat`; luồng bị ngắt thì báo lỗi và giữ câu hỏi để gửi lại. Phân tích A/B/C chọn tay vẫn dùng `/api/chat`.
- Mã đoạn mô hình chép sai, ví dụ "(chunk_id: src_…: c0000)", được bỏ khỏi câu văn; nút nguồn bên dưới vẫn còn.
- Kiểm tra: `test_chat_stream.py` (6 đạt: đọc JSON dở, không người nghe thì không stream, chữ chỉ dài thêm, thứ tự progress → done, báo lỗi 404/500 thay vì cắt luồng, Ollama ghép chữ và đọc token từ dòng cuối). Frontend `npm test` 6 đạt. Backend toàn bộ 295 đạt, 1 lỗi ở `test_rename_keeps_order_and_activity_time` (kiểm thử chập chờn đã biết; chạy riêng thì đạt).
- Chạy thật với qwen3:4b. Câu ngắn: tiến trình đến ngay, chữ đầu tiên sau khoảng 4 giây, xong sau khoảng 6 giây. Câu 3 ý (điều kiện C): 8 bước tiến trình, chữ đầu tiên ở giây thứ 14, xong ở giây thứ 17–18, đủ 3 ý. Đã xem trên trình duyệt khổ 1024 px và 375 px: không tràn ngang.

### Đợt 3: tự phân loại tài liệu

- `backend/app/ingestion/doc_type.py`: luật nhận dạng cố định, không gọi mô hình. Dựa vào tiêu đề (8 dòng đầu, tên tệp) và dấu hiệu trong thân như "Bên A/Bên B", "Căn cứ", "Số: 12/2020/", "Điều", "MSSV", "ĐTB", "FR-01". Có 8 nhãn: Hợp đồng, Quy chế, Nội quy, Bảng điểm, Văn bản pháp quy, Đặc tả phần mềm, Bài giảng, Khác. Không đủ dấu hiệu thì trả "Khác", không đoán.
- Nhãn lưu ở `knowledge_sources.display_metadata` (`doc_type`, `doc_type_by` = `auto` hoặc `user`), không cần migration. Ghi lúc tải lên; tài liệu nạp trước đợt này được phân loại bù từ 3 đoạn đầu khi liệt kê (một lần). Nhãn người dùng đã sửa được giữ khi nạp lại cùng tệp.
- Sửa nhãn: `PUT /api/sources/{id}/doc-type`, chỉ người tải lên; trên giao diện là ô chọn ở nhãn loại, trang Hồ sơ tài liệu. Danh sách tài liệu cá nhân và tổ chức trả thêm `doc_type`. Chưa dùng mô hình đọc trang đầu như mục 3.4 mô tả, và chưa "học từ người dùng".
- Kiểm tra: `test_doc_type.py` (7 đạt: 6 loại chính, tên tệp chung chung, trường hợp không chắc, bài giảng, lưu và giữ nhãn sửa tay, chỉ người tải lên được sửa, phân loại bù tài liệu cũ). Backend toàn bộ 302 đạt, 1 lỗi ở kiểm thử chập chờn đã biết. Chạy thật qua API với 6 tài liệu mẫu: 6/6 đúng loại, gồm `noi-quy-mau.txt` nạp từ trước. Trên trình duyệt: đổi nhãn rồi tải lại trang thì nhãn mới vẫn giữ; khổ 375 px không tràn ngang.

### Đợt 4: ô chat Tự động, lệnh "/", thẻ kết quả (chủ dự án duyệt bản làm thử 19/11)

- `analysis/skill_router.py` + `POST /api/studio/route`: luật cố định. Câu khớp đúng một kỹ năng (Kiểm tra điều kiện, Quy trình từng bước, Ai duyệt, Rà soát hợp đồng, Hiệu lực văn bản), và có tài liệu đúng loại khi kỹ năng cần, thì gọi kỹ năng đó. Khớp nhiều kỹ năng hoặc không khớp thì để pipeline sản phẩm tự chọn trả lời thẳng hay dùng nhiều tác tử. Trường `skill` dùng khi người dùng gọi bằng "/". Thực nghiệm A/B/C không đi qua đây.
- Ô chat chỉ còn chế độ "Tự động"; menu Phân tích A/B/C đã bỏ khỏi ô chat (A/B/C còn ở trang Thực nghiệm). Gõ "/" để chọn kỹ năng. Kết quả kỹ năng hiện thành thẻ (`components/SkillCard.tsx`), căn cứ bấm được.
- Thẻ lưu vào cuộc trò chuyện (`POST /api/conversations/skill-card`): tin nhắn trợ lý gồm dòng tóm tắt và dữ liệu thẻ trong `<!--skill-card:…-->`. Ngữ cảnh hội thoại cho mô hình chỉ lấy dòng tóm tắt (`conversation_context.py`). Tải lại trang thẻ vẫn còn; câu hỏi tiếp nối hiểu đúng ngữ cảnh. Chưa có sửa thẻ bằng lời.
- Lỗi gặp khi chạy thật: kỹ năng Ai duyệt trả "Trưởng phòng" cho đơn nghỉ 6 ngày, trong khi quy định là "từ 5 ngày trở lên do Giám đốc khối duyệt". Đã sửa: ngưỡng số ngày do luật cố định so sánh (`approver_by_days`), có kiểm thử chặn tái phát.
- Kiểm tra: `test_skill_router.py` (7), `test_domain_tools.py` thêm 2. Backend toàn bộ 312 đạt. Chạy thật trên trình duyệt: Ai duyệt (6 ngày, ra Giám đốc khối), Kiểm tra điều kiện (ĐTB 3,4 và rèn luyện 65, ra Không đủ điều kiện, từng điều kiện có căn cứ), "/Rà soát hợp đồng" (1 điều khoản rủi ro Cao kèm nguyên văn). Khổ 375 px không tràn ngang. Sau khi lưu thẻ: tải lại trang thẻ vẫn còn; câu tiếp nối "Quyết định này do cơ quan nào ban hành?" đi qua pipeline, trả lời đúng, có nguồn. Kỹ năng Quy trình từng bước trên quyết định mẫu chỉ ra 1 bước, vì tài liệu mẫu không mô tả thủ tục (giới hạn của tài liệu thử, không phải của bộ định tuyến).
- Kiểm tra cuối đợt: `test_skill_card_context.py` (2), frontend `tests/skillMessage.test.mjs` (2). Backend toàn bộ 314 đạt; frontend `npm test` 8 đạt, `tsc` và `build` đạt.

### Đợt 9: hàng đợi khi nhiều người hỏi, nhật ký truy cập tài liệu Mật

- Hàng đợi (`research/run_queue.py`): ô chat sản phẩm giới hạn số lượt chạy đồng thời (`PRODUCT_MAX_CONCURRENT_RUNS`, mặc định 1). Người đến sau xếp hàng theo thứ tự, luồng stream báo `{"type":"queue","position":N}` và giao diện hiện "Đang chờ lượt, thứ tự N". Người bỏ đi khi đang chờ thì rời hàng, người sau lên một bậc; lượt bị lỗi vẫn trả chỗ. Hàng đợi ở cấp lượt chạy (không ở từng lời gọi mô hình) nên thời gian đo không lẫn thời gian chờ; thực nghiệm A/B/C và các kỹ năng gọi riêng chưa đi qua hàng đợi.
- Lỗi gặp khi chạy thật: lời báo thứ tự lọt vào luồng của người vừa chạy xong, vì `emit` đọc ngữ cảnh của bên gọi. Đã sửa bằng `bound_emit()` (gắn với người đang chờ lúc vào hàng); có kiểm thử 3 người chặn tái phát.
- Nhật ký tài liệu Mật (`core/secret_audit.py`, bảng `org_secret_access`, migration `20261119_15`, chỉ thêm bảng): ghi khi mở tài liệu hoặc đoạn (VIEW) và khi AI được đưa đoạn của tài liệu đó trong một lượt trả lời (ASK). Chỉ tài liệu mức Mật của tổ chức; không ghi nội dung câu hỏi. Xem ở trang Tổ chức, tab Tài liệu, chỉ Ban giám đốc và chủ tổ chức (`GET /api/org/spaces/{id}/secret-access`; Trưởng phòng và nhân viên nhận 403). Ghi nhật ký lỗi thì không chặn người dùng (chỉ ghi log lỗi). Chưa ghi khi kỹ năng (Rà soát hợp đồng…) đọc tài liệu Mật.
- Kiểm tra: `test_run_queue.py` (5), `test_org_api.py` thêm 2. Backend toàn bộ 321 đạt; frontend `tsc`, `build`, `npm test` 8 đạt. Chạy thật 3 người hỏi cùng lúc: người 1 không chờ, người 2 thứ 1, người 3 thứ 2 rồi thứ 1, cả 3 có câu trả lời, không lỗi. Chạy thật tổ chức thử có tài liệu Mật: 1 lượt VIEW và 1 lượt ASK được ghi và hiện trên trang Tổ chức.

### Đợt 5: tác tử theo loại việc (nhóm đã đồng ý 19/11)

- Bộ mới `work` trong `research/registry.py`: 4 tác tử chuyên môn dùng chung mọi ngành (Điều kiện và quy định, Quy trình và phê duyệt, Điều khoản và cam kết, Số liệu và tính toán) + Chuyên viên tổng hợp. Ô chat sản phẩm mặc định dùng bộ này (`domain_pack` trống + `product_mode`). Bộ Phần mềm và A/B/C của thực nghiệm giữ nguyên (`test_software_is_default_and_prompts_unchanged` vẫn đạt).
- Ngành là kiến thức nạp thêm: theo loại tài liệu trong phạm vi hỏi (nhãn đợt 3), tác tử nhận thêm ghi chú. Ví dụ: hợp đồng thì tác tử Điều khoản đối chiếu Điều 398 BLDS 2015; nội quy thì tác tử Số liệu tính theo tỷ lệ tháng (`WORK_KNOWLEDGE`).
- Chọn tác tử (`research/agent_selection.py`): so ý nghĩa câu hỏi với mô tả tiếng Việt của từng tác tử bằng nomic-embed-text (cùng mô hình nhúng tài liệu), từ khóa cộng điểm; giữ tối đa 3 tác tử chuyên môn + Tổng hợp; bộ lập kế hoạch chỉ được dùng các tác tử đã chọn. Điểm sát nhau mà không có từ khóa thì chỉ giao Tổng hợp, không đoán. Lựa chọn ghi vào `effective_config.agent_selection` và sự kiện `agent_selection`; ô chat hiện "Chọn tác tử: …". Nút "Theo tác tử" hiện cho lượt chat sản phẩm có nhiều nhiệm vụ.
- Chưa làm: hỏi lại bằng 2 nút khi mơ hồ (hiện giao Tổng hợp); học từ người dùng khi họ sửa nhãn hoặc chọn lại tác tử.
- Ví dụ mục 3.4 (hợp đồng máy chiếu + cấp duyệt), chạy thật với qwen3:4b: chọn Điều khoản, Quy trình, Tổng hợp; kế hoạch 2 nhiệm vụ (T1 điều khoản, T2 quy trình); câu trả lời nêu phạt 8% (Điều 7) và nói rõ tài liệu không có quy chế chi tiêu. Lần chạy đầu chỉ chọn được Điều khoản, vì từ khóa thiếu "duyệt" đứng riêng; đã thêm.
- Đo tỷ lệ chọn đúng (`scripts/research/agent_routing_eval.py`, bộ `data/research/agent-routing-v1`, 32 câu, kết quả thô `results-2026-11-19.json`), không gọi mô hình sinh:
  - Theo loại việc, chỉ từ khóa: 31/32 = 96,9% (CI 95% Wilson 84,3–99,4%).
  - Theo loại việc, ý nghĩa + từ khóa (cách đang dùng): 28/32 = 87,5% (71,9–95,0%). Sai 2 câu lẽ ra giao Tổng hợp ("Tóm tắt…", "Xin chào"), 1 câu cảnh báo học tập, 1 câu thẩm quyền đăng ký kinh doanh.
  - Cách cũ theo ngành (chỉ đo được có nhận ra tác tử chuyên môn hay không, vì nhãn khác nhau): chọn đúng ngành 24/28 = 85,7%; để mặc định Phần mềm 1/28 = 3,6%.
  - Hạn chế: bộ câu hỏi và từ khóa do cùng nhóm phát triển soạn (có trợ lý AI), nên kết quả "chỉ từ khóa" bị thổi phồng; chưa có câu người ngoài nhóm soạn, chưa tách held-out. Không chỉnh thuật toán theo bộ này. Cần bộ do người ngoài nhóm soạn trước khi kết luận cách nào tốt hơn hoặc báo cáo hội đồng.
- Kiểm tra: `test_agent_selection.py` (5). Backend toàn bộ 326 đạt; frontend `npm test` 8 đạt, `tsc` đạt.

### Đợt 6: bố cục 7 trang (chủ dự án chọn làm cả bố cục, 19/11)

- Thanh bên theo mục 2b: Không gian làm việc, Thư viện tài liệu, Kết quả đã lưu, Việc cần làm (chỉ khi đang mở tổ chức), Tổ chức, Tổng quan, Cài đặt. Nhóm Nghiên cứu (Phòng đánh giá, Thực nghiệm, Chấm mù) chỉ hiện cho quản trị hệ thống hoặc khi bật "Chế độ nhà nghiên cứu" ở Cài đặt. Hệ thống chưa có vai trò nhà nghiên cứu riêng, nên đây là tùy chọn hiển thị theo trình duyệt (`utils/researchMode.ts`), không phải phân quyền. Nhóm Quản trị giữ nguyên.
- Thư viện tài liệu (`LibraryView.tsx`): lọc theo loại tài liệu (nhãn đợt 3, sửa tại chỗ), tìm theo tên, sắp xếp, mức mật, số đoạn; mở Hồ sơ của đúng tài liệu, hỏi về tài liệu, thêm tài liệu. Hồ sơ tài liệu và Kiểm tra mâu thuẫn không còn trên thanh bên, mở từ Thư viện.
- Kết quả đã lưu (`SavedResultsView.tsx`): danh sách báo cáo đã lưu (`/studio/reports`), lọc theo loại, mở lại ở công cụ đã tạo, xóa có xác nhận.
- Việc cần làm (`TasksView.tsx`): thông báo của tổ chức (dùng chung câu chữ với chuông) và đánh dấu đã đọc. Đơn từ và duyệt theo cấp ghi rõ là chưa có (đợt 10), không giả lập.
- Cài đặt (`SettingsView.tsx`): tài khoản, đổi ảnh đại diện, giao diện sáng/tối, chế độ nhà nghiên cứu, lối sang Thư viện để sửa nhãn; kết nối nguồn tài liệu ghi rõ chưa có.
- Đã bỏ: ô chọn lĩnh vực trong menu không gian và trang Bộ công cụ trên thanh bên. Bộ công cụ theo ngành vẫn mở được bằng lệnh "/" trong ô chat (để không mất 9 công cụ chưa thành kỹ năng chat); chọn ngành ngay trong trang bộ công cụ. Ô chat sản phẩm không gửi lĩnh vực nữa (backend dùng tác tử theo loại việc). Phân tích A/B/C chọn tay và kỹ năng vẫn dùng lĩnh vực đã lưu của không gian.
- Kiểm tra trên trình duyệt 1024 px: không gian cá nhân có 6 mục, tổ chức có 7 mục; Thư viện lọc đúng, mở đúng hồ sơ; Kết quả đã lưu hiện trạng thái trống; bật chế độ nhà nghiên cứu thì nhóm Nghiên cứu hiện; "/công cụ" mở Bộ công cụ. Khổ 375 px: không tràn ngang, không nút nào dưới 44 px. Backend 326 đạt; frontend `tsc`, `build`, `npm test` 8 đạt.

### Tiếp nối 19/11: phần còn dở và Đợt 10 (các mục không cần thư viện mới)

- Nhật ký Mật cho kỹ năng: mọi kỹ năng lấy đoạn tài liệu qua `_case_evidence` / `_all_chunks` (`api/analysis.py`), nên đoạn của tài liệu Mật đưa cho kỹ năng cũng được ghi (ASK). Kiểm thử `test_skill_reading_secret_doc_is_logged`.
- Hỏi lại khi mơ hồ (mục 3.4): không khớp kỹ năng mà hai tác tử sát điểm nhau (so ý nghĩa) thì `/api/studio/route` trả `clarify` với câu hỏi và 2 lựa chọn; ô chat hiện 2 nút và nút "Sửa câu hỏi". Bấm nút thì câu hỏi được gửi lại với `agent` đã chọn (`ChatRequest.agent`, ghi `method = user_choice` trong `agent_selection`). Câu dưới 5 từ (như "Xin chào") không hỏi lại mà giao Chuyên viên tổng hợp. Kiểm thử ở `test_agent_selection.py` (2). Chưa gặp ca mơ hồ khi chạy thật trên trình duyệt, nên giao diện 2 nút mới được kiểm qua kiểm thử API.
- Đơn từ và duyệt theo cấp: bảng `org_requests` (migration `20261119_16`, chỉ thêm bảng); API `/api/org/spaces/{id}/requests` (tạo, xem, duyệt hoặc từ chối kèm ghi chú, rút đơn); quyền `can_decide_request` (Ban giám đốc duyệt mọi đơn, Trưởng phòng duyệt đơn cấp phòng của phòng mình, không tự duyệt đơn của mình); lịch sử duyệt; thông báo qua chuông cho người duyệt và người gửi. Giao diện ở trang Việc cần làm: tạo đơn, nút "Kiểm tra theo quy định" (kỹ năng Ai duyệt + Kiểm tra điều kiện, gợi ý cấp duyệt bằng luật `utils/approverLevel.ts`; người gửi vẫn tự chọn cấp), danh sách chờ tôi duyệt và đơn tôi đã gửi. Kiểm thử: `test_org_api.py` thêm 2, `approverLevel.test.mjs`.
- Theo dõi tài liệu mới (`analysis/watch.py`): mỗi lần tải tài liệu, kiểm bằng luật cố định có sẵn (hiệu lực văn bản, cặp câu khác con số hoặc khác phủ định) so với tài liệu cũ. Có phát hiện thì báo người tải lên qua chuông, kết quả trả kèm trong phản hồi tải lên (`watch`). Không gọi mô hình. "Có thể mâu thuẫn" là cặp nghi vấn, cần mở Kiểm tra mâu thuẫn để xác nhận. Chưa báo cho người khác khi tài liệu được nộp vào tổ chức. Kiểm thử `test_doc_watch.py` (4).
- Chạy thật: nạp "Quyết định 99/2026 … thay thế 12/2020" thì có thông báo "thay thế qd_12_2020.txt" và 1 cặp câu nghi vấn (câu ngày hiệu lực khác nhau). Tài khoản thử thứ hai vào tổ chức thử, gửi đơn nghỉ 6 ngày cấp Ban giám đốc; chủ tổ chức thấy đơn, duyệt, người gửi nhận thông báo, lịch sử có 2 bước. Trang Việc cần làm ở khổ 375 px: không tràn ngang, không còn ô nào dưới 44 px.
- Backend toàn bộ 335 đạt; frontend `tsc`, `build`, `npm test` 9 đạt.
- Đợt 10 còn lại, cần hỏi trước: OCR (thư viện mới), đăng nhập tổ chức (Google/Microsoft/LDAP), kết nối nguồn ngoài (Drive/SharePoint), bộ cài cho khách, xuất Word theo mẫu cơ quan (cần mẫu thật của trường/khoa).

### Rà soát từng trang và sửa lỗi (19–20/11)

Kiểm tra mọi trang (10 trang thanh bên + Hồ sơ tài liệu, Kiểm tra mâu thuẫn, 15 công cụ của Bộ công cụ) ở khổ 1280 px và 375 px, giao diện sáng và tối, bằng đo DOM: lỗi console, tràn ngang, chữ "undefined/NaN", chữ bị cắt, robot che nút, nút dưới 44 px, độ tương phản. Lỗi tìm thấy và đã sửa:
- Robot che nút trong thẻ có nền (bản đồ chỗ trống không đi vào thẻ nên bỏ sót nút bên trong): tô thêm nút/ô nhập bên trong thẻ với trọng số cao. Đo lại với hiệu ứng tắt: không trang nào bị che.
- Bảng tìm nhanh Ctrl K mất chữ khi gõ ngay sau khi mở (đặt tiêu điểm bằng hẹn giờ 10 ms): đặt tiêu điểm ngay khi mở.
- Đổi giao diện sáng/tối có thể kẹt khi trang không hiển thị (View Transition chờ khung hình): đổi ngay khi trang ẩn.
- Tương phản: chữ phụ `--faint` chỉ 2,4:1 trên nền trắng (thời gian, "1 đoạn", "—" chưa đo…) → 4,5:1 (sáng) và 4,75:1 (tối); ô lọc Thư viện ở chế độ tối 2,3:1; nút trang Tổng quan chế độ tối 1,2:1; ô chủ đề nổi bật 2,8:1. Đo lại: không còn chữ dưới 3:1 trên các trang đã đo.
- Điện thoại: ô nhập (tìm tài liệu, lọc nhật ký, Phòng đánh giá, Chấm mù, form đơn từ) dưới 44 px → quy tắc chung 44 px cho ô nhập.
- Lập hồ sơ tài liệu (và mâu thuẫn, gói thiết kế, chất lượng yêu cầu, rà soát tiêu chí) trong không gian tổ chức báo lỗi đỏ vì báo cáo cá nhân không lưu nội dung tổ chức: bỏ qua bước lưu, hiện nhãn "Không lưu trong tổ chức"; Phòng đánh giá báo lý do rõ ràng.
- Kết quả đã lưu → Mở: mở đúng tài liệu của hồ sơ (trước mở tài liệu đầu danh sách).
- Kiểm tra mâu thuẫn và theo dõi tài liệu mới coi "QĐ mới thay thế QĐ cũ, ngày hiệu lực khác nhau" là mâu thuẫn mức Cao: luật cố định nhận quan hệ thay thế (`replacement_pairs`) → ghi "văn bản cũ đã bị thay thế", không phải mâu thuẫn. API `consistency/judge` nhận thêm `source_id`.
- Nút tải tệp trong ô chat không cho chọn .docx/.xlsx dù backend đọc được: đã thêm (kèm ảnh cho OCR).
- Đợt chấm mù ghi lượt "tự quyết" thành điều kiện C (không phân biệt được khi mở mã): gắn nhãn AUTO theo bước định tuyến.
- Thực nghiệm A/B/C kiểm lại sau mọi thay đổi: vẫn bộ Phần mềm, 700 token, không chọn tác tử theo loại việc.

### Đợt 7: đo "tự quyết" (AUTO) so với "lúc nào cũng đa tác tử" (C)

- Phòng đánh giá có điều kiện AUTO (pipeline sản phẩm: câu đơn giản trả lời thẳng, yêu cầu lớn chia tác tử theo loại việc; kỹ năng không đưa vào vì đầu ra là thẻ). Kiểm thử `test_eval_auto.py`.
- Bộ `data/research/auto-vs-c-v1` (12 câu: 6 đơn giản, 6 nhiều ý, kèm ý chính), script `scripts/research/auto_vs_c_eval.py`, kết quả thô `results-2026-11-19.json` (mọi lượt, run_id, mã băm cấu hình). Chạy thật qwen3:4b, 24 lượt:
  - Token: AUTO trung bình 2.635 (CI 95% 1.417–3.854), C 4.207 (3.250–5.164); Wilcoxon p = 0,021, effect size dz = −0,76.
  - Thời gian: AUTO 11,6 giây (6,4–16,8), C 21,3 giây (15,1–27,5); p = 0,0024, dz = −0,99.
  - Độ phủ ý chính tự động: AUTO 100%, C 86,8% (73,0–100,6%); p = 0,125 (chỉ 4 cặp khác nhau), chưa có ý nghĩa thống kê.
  - Định tuyến: 3/6 câu đơn giản bị đưa sang nhiều tác tử và 2/6 câu nhiều ý được trả lời thẳng (điểm cần cải thiện của bộ định tuyến CAP1, chưa sửa vì là phương pháp).
- Hạn chế: bộ câu do nhóm soạn trên tài liệu mẫu tự viết, n = 12, chưa có held-out; độ phủ ý chính là so khớp chuỗi, không phải chất lượng. Không dùng làm kết luận chất lượng.
- Đợt chấm mù đã tạo: "Chấm mù AUTO và C · auto-vs-c-v1 (19/11)", mã **CR7YM8**, 24 câu trả lời. Chưa có điểm người chấm: cần ít nhất 2 người ngoài nhóm chấm trước khi báo cáo chất lượng. Đợt cũ 9423ZU vẫn đang chờ người chấm.

### Đợt 10: phần còn lại

- Xuất Word theo mẫu văn bản hành chính: nút "Word theo mẫu" ở mọi chỗ có xuất Word; chọn Tờ trình/Biên bản/Thông báo/Báo cáo, cơ quan, địa danh, trích yếu, người ký (điền sẵn lần sau, lưu trên trình duyệt). Tệp có phần đầu cơ quan, quốc hiệu, tiêu ngữ, ngày tháng, tên loại căn giữa, khối chữ ký, Times New Roman 13. Kiểm thử XML hợp lệ kể cả ký tự đặc biệt (`test_insights.py`). Chưa có mẫu riêng của trường/khoa (cần mẫu thật).
- Kết nối nguồn: thư mục chung trên máy chủ (`SHARED_FOLDER_PATH`); Cài đặt → "Đồng bộ ngay" nạp tệp mới vào kho cá nhân (chỉ trong thư mục cấu hình, định dạng hỗ trợ, ≤ 2 MB; tệp cùng tên bỏ qua). Chạy thật: 2 tệp hợp lệ được nạp, tệp .exe bị bỏ qua, đồng bộ lần hai bỏ qua đúng. Google Drive, SharePoint, email: chưa làm (cần tài khoản dịch vụ của tổ chức).
- OCR: ảnh (.png/.jpg/.tif) và PDF scan được nhận dạng bằng Tesseract cục bộ (`ingestion/ocr.py`, không thêm thư viện Python; PDF lấy ảnh nhúng bằng pypdf). Máy chưa có Tesseract thì báo rõ cần cài gì (`GET /api/ocr-status`). Máy này chưa cài Tesseract nên chưa chạy thật OCR; kiểm thử bằng Tesseract giả lập (`test_ocr.py`). Cài trên Windows: `winget install UB-Mannheim.TesseractOCR` rồi thêm gói tiếng Việt `vie.traineddata`.
- Bộ cài cho khách: `docker/install.ps1` (Windows) và `docker/install.sh` (Linux): kiểm tra Docker, đo RAM/CPU/GPU, gợi ý mô hình (mặc định qwen3:4b; qwen3:8b chỉ khi GPU ≥ 12 GB và người cài đồng ý), tạo `docker/.env` với mật khẩu CSDL ngẫu nhiên, bật hệ thống, tải mô hình, chờ sẵn sàng; có chế độ thử (`-DryRun`, `--dry-run`). Đã chạy chế độ thử trên máy này (15 GB RAM, GPU 6 GB → qwen3:4b); chưa chạy cài thật vào Docker.
- Chưa làm: đăng nhập bằng tài khoản tổ chức (Google, Microsoft, LDAP/AD). Cần tổ chức đăng ký ứng dụng và cấp mã client hoặc máy chủ LDAP để thử; viết mã xác thực mà không thử được với nhà cung cấp thật là rủi ro bảo mật.
- Kiểm tra cuối đợt (20/11): backend 345 kiểm thử đạt; frontend `tsc`, `build`, `npm test` 9 đạt.

### Rà soát giao diện và thử theo vai người dùng (20/11)

- Làm lại 4 trang: Kết quả đã lưu (danh sách theo ngày, tiêu đề tự xuống dòng tối đa 2 dòng thay vì tràn khỏi thẻ, tìm kiếm, lọc theo loại, cột "Tạo kết quả mới" và "Theo loại"), Thư viện (huy hiệu theo loại tệp, ô kéo thả khi kho trống, kéo thả vào bảng, ẩn hàng số khi chưa có tài liệu), Cài đặt (thẻ hồ sơ, gộp "Hiển thị", thẻ "Hệ thống" lấy mô hình/CSDL/số tài liệu thật, lưới 2 cột cân), Việc cần làm (một trạng thái trống giải thích luồng đơn, lời nhắc khi nút kiểm tra bị khóa, mục "Đơn đã xử lý"). Dòng nhỏ trên tiêu đề các trang mới không còn là chữ chung "OrchestrIQ Studio".
- Lỗi tìm ra khi đóng vai và đã sửa: chế độ nhà nghiên cứu lưu chung cho cả trình duyệt (người dùng mới cùng máy thấy nhóm Nghiên cứu) → lưu theo tài khoản; mọi người dùng thường hiện nhãn "Phát triển" → "Người dùng"; người duyệt không xem lại được đơn đã duyệt → thêm "Đơn đã xử lý"; kiểm tra điều kiện liệt kê đoạn lạc đề khi tổ chức không có quy định nghỉ phép → khi mọi điều kiện "chưa rõ" thì báo chưa thấy quy định; yêu cầu "Tạo 5 câu hỏi trắc nghiệm về quy trình…" bị ép vào kỹ năng Quy trình → yêu cầu soạn nội dung (tạo câu hỏi, tóm tắt, soạn văn bản) để bộ điều phối trả lời (`test_skill_router.py`); danh sách đánh số trong câu trả lời mất số do lớp reset CSS → thêm lại.
- Đã thử đúng: nhân viên không thấy và không hỏi ra được nội dung tài liệu Mật; người gửi đơn không tự duyệt đơn của mình; thẻ Quy trình từng bước có trích nguồn từng bước.
- Còn tồn (ghi vào tài liệu đề xuất phát triển 20/11): truy xuất bỏ sót đoạn chứa câu trả lời (hỏi "CSDL gồm những bảng nào" chỉ lấy đoạn đầu các tài liệu, trả lời "không có thông tin" dù tài liệu có mục danh sách bảng; sửa phải đụng phần truy xuất dùng chung với điều kiện C nên cần nhóm đồng ý); lượt hỏi lại của kỹ năng điều kiện ép mô hình tìm điều kiện cả khi tài liệu không liên quan; tạo câu hỏi trắc nghiệm trong ô chat chưa có phương án và đáp án; người duy nhất ở một cấp gửi đơn lên chính cấp đó thì không ai duyệt được; bộ tài liệu mẫu chỉ có ngành phần mềm; "Chính sách bảo mật" bị nhận là văn bản pháp quy.
- Kiểm tra: backend 346 đạt; frontend `tsc`, `build`, 9 kiểm thử đạt; 4 trang không tràn ngang ở 375 px, đã xem sáng/tối.

## Chưa có hoặc chưa làm

- Lượt chạy thực nghiệm (trang Thực nghiệm) chưa lọc theo không gian; chỉ tài liệu và cuộc trò chuyện được gán không gian.
- Chưa có tạo hoặc khóa cấu hình. Cấu hình CAP1 lấy từ biến môi trường; Studio chỉ hiển thị kèm `config_hash`.
- Ở trang Thực nghiệm chưa có token theo từng tác tử, token tiết kiệm, độ phủ nhiệm vụ (hiện "Chưa đo"). Gói thiết kế đo token theo từng tác tử; Phòng đánh giá đo độ phủ ý chính tự động và điểm người chấm.
- Chưa có diễn tập nghẽn LLM và đăng nhập Google/GitHub. Đã bỏ khỏi giao diện, không giả lập.
- Điều kiện B và C của CAP1 thường bị từ chối ở bước kiểm tra kế hoạch với yêu cầu dài nhiều ý (rà soát 11/11: cả B và C từ chối yêu cầu "Thiết kế cổng thanh toán chống trừ tiền hai lần… và phân quyền truy cập"). Đây là hành vi sẵn có của CAP1, không do tích hợp. Studio báo lỗi bằng tiếng Việt và giữ nguyên thông báo gốc.
- Ngôn ngữ trả lời (chế độ Hỏi nhanh): câu hỏi có dấu tiếng Việt thì có thêm lời nhắc cuối prompt "trả lời bằng tiếng Việt, gọn khoảng 150 từ" (qwen3:4b hay trả lời theo ngôn ngữ của tài liệu tiếng Anh; giới hạn 700 token đầu ra làm câu dài bị cụt). Điều kiện A/B/C dùng cho thực nghiệm không đổi. Chạy thật 11/11: 6/7 câu mẫu trả lời tiếng Việt, câu tiếng Anh vẫn trả lời tiếng Anh.
- Chế độ Hỏi nhanh của CAP1 chỉ đi đường hỏi đáp trực tiếp khi câu có dạng câu hỏi (dấu "?" hoặc từ hỏi). Câu mệnh lệnh như "Giải thích các thuật ngữ…" bị chuyển sang lập kế hoạch nhiều bước và thường báo không có bằng chứng. Câu hỏi mẫu của Studio đã viết dạng câu hỏi; luật định tuyến của CAP1 giữ nguyên.
- Câu trả lời của mô hình đôi khi là JSON bị cụt; Studio lấy phần trả lời đọc được và ghi chú "bị cắt", không sửa nội dung.
- Dữ liệu 60 lượt pilot R4 của C1SE.27 **không mang sang**: đo trên backend cũ, không tái lập trên pipeline CAP1.
- Chưa có kết luận chất lượng nào. Mọi số là số mô tả kỹ thuật.
