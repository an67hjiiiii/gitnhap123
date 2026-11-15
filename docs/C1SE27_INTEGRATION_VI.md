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

CAP1 có hai vai trò: USER và ADMIN. Mỗi người chỉ thấy và xóa được tài liệu, cuộc trò chuyện, lượt chạy của chính mình (máy chủ kiểm tra). ADMIN thấy thêm trang Cơ sở dữ liệu; các API `/api/studio/admin/*` trả 403 với USER. Bốn vai trò cũ của C1SE.27 (developer, tech_lead, researcher, admin) không mang sang.

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

## Điều kiện thực nghiệm và profile backend

Điều kiện nào chạy được do `IMPLEMENTATION_PROFILE` của backend quyết định (xem `GET /api/config` → `allowed_conditions`):

| Profile | Điều kiện chạy được |
| --- | --- |
| `m0` (mặc định) | A |
| `m1` | A, B, C |
| `m2` hoặc `dev` | A, B, C, C-P, C-N, C-O |

- Muốn chạy **C-P / C-N / C-O** trong Phòng đánh giá: khởi động backend với `IMPLEMENTATION_PROFILE=m2` (hoặc `dev` khi chỉ kiểm thử kỹ thuật), ví dụ `$env:IMPLEMENTATION_PROFILE="m2"` rồi chạy `start-backend.ps1`.
- Giao diện đọc `allowed_conditions` và khoá các điều kiện chưa được phép, kèm nhãn "cần profile m2", để bấm vào không còn ra lỗi 400.
- `dev` chỉ dành cho kiểm thử kỹ thuật, không dùng để công bố kết quả mốc.
