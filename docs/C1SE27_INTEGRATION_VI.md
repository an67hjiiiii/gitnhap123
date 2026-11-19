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
