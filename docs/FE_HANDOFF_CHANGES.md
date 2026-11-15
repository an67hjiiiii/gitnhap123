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

Với SSE, hiển thị tiến trình bằng `events[eventName]`; unknown event dùng thông báo chung. Gửi `Last-Event-ID` khi nối lại. `GET /runs/{id}` và SSE `GET /runs/{id}/events` nằm trong bucket riêng (mặc định 600 request/phút/người dùng, `REVIEW_RATE_STATUS_PER_MIN`), không bị giới hạn 60/phút của các request đọc khác; vẫn nên ưu tiên SSE hơn polling.

`route.decided.data.reasons` là danh sách mã cùng tham số. Với các event verdict, dùng `code` để chọn thông điệp, còn `params` có thể dùng để bổ sung chi tiết có cấu trúc. `pipeline.trace` cũng được phát ở condition A, khi một số trường chi tiết là `null`.

## Giới hạn và hành vi

- `task_budget` và `pipeline.trace` mô tả ngân sách/tiến trình; không diễn giải trace như kết quả cuối.
- `verdict.slots_missing` báo những chi tiết còn thiếu trong `params.missing_slots`.
- Giới hạn mặc định: `request_text` 20.000 ký tự; requirement và `edited_text` 2.000; tối đa 100 requirement mỗi case. Các giới hạn nội dung có thể cấu hình bằng (đặt khi khởi động tiến trình; có thể nâng hoặc hạ, OpenAPI `maxLength` theo giá trị đã đặt) `REVIEW_MAX_REQUEST_CHARS`, `REVIEW_MAX_REQUIREMENT_CHARS`, `REVIEW_MAX_REQUIREMENTS_PER_CASE`.
- Budget gửi lên bị chặn theo `REVIEW_MAX_REQUIREMENTS` (mặc định 100), `REVIEW_MAX_SECONDS` (3600), `REVIEW_MAX_TOKENS`, `REVIEW_MAX_MODEL_CALLS`; phản hồi trạng thái job echo budget hiệu lực.
- Mỗi người dùng mặc định có 2 lần bắt đầu chạy/phút , 60 request Review khác/phút và 600 request/phút cho trạng thái run + SSE. Cấu hình bằng `REVIEW_RATE_RUNS_PER_MIN`, `REVIEW_RATE_READS_PER_MIN`, `REVIEW_RATE_STATUS_PER_MIN` (0 = tắt); 429 có `Retry-After`.
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
| `REVIEW_RATE_STATUS_PER_MIN` | Giới hạn riêng cho `GET /runs/{id}` và SSE (mặc định 600). |

`task_budget`, `pipeline.trace`, giới hạn body và các trường trên được giữ theo hợp đồng hiện hành; FE nên đọc OpenAPI snapshot thay vì tự suy đoán thêm trường.

## Lỗi một yêu cầu (task.failed)
- Khi pipeline trả run FAILED, finding vẫn là UNDETERMINED (evidence rỗng; trước đây giữ evidence nếu có) và có thêm event pipeline.trace + 	ask.failed với error_type thuộc: PLAN_REJECTED, PROVIDER_LIMIT, CONDITION_NOT_AVAILABLE, PIPELINE_RUN_FAILED, UNKNOWN. error luôn là thông điệp cố định; chi tiết chỉ ở log máy chủ.
- Nhãn tiếng Việt ở contracts/review/labels.vi.json mục 	ask_failed (what/todo).

## Export Markdown: dòng Edited (2026-11-14)
Khi quyết định là EDIT và có edited_text, export thêm dòng `   - Edited: <văn bản>` sau dòng Decision. Thay đổi cộng thêm, không đổi cấu trúc cũ.

## Hội thoại: intent, bộ nhớ, đường xử lý, stream tiến độ (2026-11-14)
**`POST /api/chat`** (đổi, tương thích ngược: chỉ thêm trường)
- Trả thêm: `intent {intent, reason, language}` (intent ∈ greeting|thanks|farewell|out_of_scope|about_system|document_question|follow_up|ambiguous), `route` (`{path:"B"|"C", reason, params, executed}` hoặc `null`), `rewritten_query` (câu độc lập đã viết lại cho câu nối tiếp, hoặc `null`).
- Chào/cảm ơn/tạm biệt/ngoài phạm vi/hỏi về hệ thống: trả lời ngay, KHÔNG truy hồi, KHÔNG gọi pipeline: `run_id: null`, `status: "COMPLETE"`, `citations: []`, `events: [{stage:"intent_routed", retrieval:false, …}]`. FE không được giả định luôn có `run_id`.
- Câu có tham chiếu ("còn cái đó thì sao?", "What about that?") được viết lại thành câu độc lập bằng 1 lượt model nhỏ; hội thoại dài hơn 6 tin được tóm tắt cuốn chiếu (1 lượt model, có cache theo hội thoại), 6 tin gần nhất giữ nguyên văn.
- Một ý → đường B (một lượt truy hồi + trả lời); nhiều ý → `route.path:"C"` nhưng mặc định VẪN chạy một lượt có căn cứ (`route.executed:"B"`); chỉ lập kế hoạch nhiều bước khi đặt `CHAT_FORCE_PLAN=1` (`executed:"C"`). Lý do: trong thử nghiệm cục bộ đường lập kế hoạch chậm 3–8 lần và làm mất một số câu trả lời mà một lượt tìm được. Event `route_chosen` nằm cuối `events`.
- Văn phong: trả lời tiếng Việt tự nhiên, ngắn, nêu "theo tài liệu <tên>"; thiếu thông tin thì nói rõ và gợi ý bước tiếp. Câu NO_EVIDENCE cố định mới: "Mình chưa tìm thấy thông tin này trong các tài liệu đã tải lên. Bạn có thể tải thêm tài liệu liên quan hoặc hỏi cụ thể hơn (ví dụ nêu tên mục hoặc giá trị cần tìm), mình sẽ tra lại." Dòng "Nguồn: [chunk_id]" giữ nguyên.

**`POST /api/chat/stream`** (mới): cùng body với `/api/chat`, trả `text/event-stream`.
- `event: status` data `{step, text}` nhiều lần (step: routing, rewriting, route, understanding, planning, plan_ready, searching, step_done, writing…; text tiếng Việt sẵn để hiển thị);
- kết thúc bằng `event: done` data = đúng body của `/api/chat`, hoặc `event: error` data `{http_status, code, message, hint}` (thông báo thân thiện, không lộ stack). Lỗi trước khi stream (400/404…) cũng đi qua `event: error`.

**Review SSE** (events mới): `route.chosen {case_id, requirement_id, path, reason, params}` khi engine chạy ở `condition=AUTO` (một ý → B, nhiều ý → C, không có C ở hồ sơ hiện tại → B với `C_NOT_AVAILABLE`); `plan.ready {case_id, requirement_id, steps:[{task_id, goal, domain, depends_on}]}` khi run C có ≥2 bước (để FE hiển thị kế hoạch).
**labels.vi.json**: thêm các mục `progress`, `friendly_errors`, `route_reason` (tiếng Việt, UTF-8).
**ResearchPipeline.run**: tham số mới `on_event` (callback đồng bộ) và `force_plan` (nội bộ).

## Kiểm tra hợp đồng FE ↔ BE qua proxy Vite (RUN_WEB.ps1 -Fake, kho PostgreSQL tạm)

Đã gọi qua `http://127.0.0.1:5173/api/*`. Không có 4xx/5xx do lệch hợp đồng ở các đường chính.

| Chức năng | FE gọi | BE trả | FE cần sửa |
|---|---|---|---|
| Đăng nhập/phiên | POST /auth/login, GET /auth/session | 200 | Không |
| Tải tài liệu | POST /sources/file | 200 `source_id` | Không |
| Chat (nghiên cứu, condition=A) | POST /chat | 200, có `run_id` | Không |
| Chat (sản phẩm) chào hỏi | POST /chat product_mode | 200, `run_id: null` | Chịu được `run_id` null (FE_PROPOSALS #2) |
| Chat (sản phẩm) hỏi tài liệu, nối tiếp | POST /chat + conversation_id | 200 | Không |
| Chat stream | POST /chat/stream | 200, SSE kết thúc bằng `done` | FE chưa dùng (đề xuất #3) |
| Lịch sử | GET /runs, /runs/{id}, /conversations(/{id}) | 200 | Không |
| Review: tạo/đề xuất/xác nhận yêu cầu | POST /review/cases, :propose, PUT requirements | 201/200/200 | Không |
| Review: chạy + SSE tiến độ | POST /review/cases/{id}/runs, GET /review/runs/{id}/events | 202, sự kiện route.decided→job.done | Không |
| Review: quyết định, xuất | PUT findings/{id}/decision, GET export | 200 | Không |
| Studio workspaces/admin | GET /studio/workspaces, /studio/admin/* | 503 nếu kho file; 200 với PostgreSQL | Hiện thông báo cần PostgreSQL (đề xuất #5) |

## Điều phối thông minh hơn (W-I)

Chỉ thêm, không đổi hợp đồng cũ.

- **`route.executed`** có thêm giá trị `"C_MULTI"`: câu nhiều ý (route C) được truy hồi riêng từng ý rồi gộp vào một bối cảnh, một lượt trả lời. `"B"` và `"C"` (kế hoạch nhiều bước, chỉ khi `CHAT_FORCE_PLAN=1`) giữ nguyên. Tắt bằng `CHAT_MULTI_RETRIEVAL=0`.
- **Sự kiện mới trong `events` của run** (và thành dòng `status` trong `/api/chat/stream`, nhãn lấy từ `labels.vi.json` mục `progress`):

| stage | khi nào | trường | nhãn tiếng Việt |
|---|---|---|---|
| `retrieval.multi` | câu có ≥2 ý | `ideas[]`, `dependent`, `queries` | Câu hỏi có {n} ý, mình tìm riêng từng ý rồi gộp lại… |
| `retrieval.retry` | kết quả tìm yếu (luật), tối đa 1 lần | `reasons[]` (`NO_CANDIDATES`/`FEW_STRONG`/`MISSING_QUANTITY`), `rewritten_query`, `top_k`, `before`, `after`, `gained[]` | Kết quả tìm còn yếu, mình thử lại một lần với cách diễn đạt khác… |
| `answer_guard` | câu trả lời bị lọc/đối chiếu | `notes[]` (`TRAILING_NEGATIVE_DROPPED:n`, `UNSUPPORTED_NUMBER_DROPPED:…`, `VERIFY_RAN`, `VERIFY_DROPPED:n`, `VERIFY_FLAGGED_KEPT:n`) | Đã đối chiếu câu trả lời với tài liệu. (chỉ hiện khi có `VERIFY_RAN`) |

- Thứ tự một lượt chat: `routing` → (`rewriting`) → (`translating`) → `route` → `retrieval.multi` → `retrieval.retry` → `answer_guard`. Mọi bước đều tuỳ chọn trừ `routing` và `route`.
- Biến môi trường (chỉ đọc trong BE): `RETRIEVAL_FUSION=bm25|off` (mặc định `bm25`: BM25 gộp với truy hồi hiện có bằng RRF), `RETRIEVAL_RETRY=0` tắt thử lại, `EMBEDDING_DIMENSION` (cho bge-m3 = 1024).
- FE không cần sửa để chạy; để hiện vết điều phối, đọc `events[].stage` ở trên hoặc dòng `status` của stream.

## Đợt 2 — chế độ Phân tích và đường trả thẳng (chỉ thêm, không đổi khoá cũ)
- `task_results[i].metrics` (mới, mọi khoá là số nguyên >= 0): `input_tokens, output_tokens, latency_ms, valid_citations, invalid_citations, retrieved_chunks`. Không có `agent_results` ở BE; FE dựng từ `task_results`.
- Event `planning_degraded` `{reason, errors, fallback:"C_MULTI"}`: kế hoạch hỏng sau 1 lần sửa thì trả lời trực tiếp, run `PARTIAL` thay vì lỗi.
- Câu trả lời tổng hợp: phần thân do mã ghép theo miền (giữ nguyên trích dẫn), model chỉ viết mục "Tóm tắt" ngắn; lỗi model thì bỏ mục này.
- Chat trả thẳng (không truy xuất, `run_id=null`): event `intent_routed` có `path` = `DIRECT` | `HISTORY` | `EMPTY_STORE`, `grounded:false`; câu kiến thức chung kèm ghi chú "Không dựa trên tài liệu của bạn". Intent mới: `general_knowledge`, `history_answer`; `intent.reason` có thể là `DEFINITION`, `SELF_CONTAINED`, `HISTORY_CUE`, `GATE_DOCUMENT_MATCH`, `HISTORY_MISS`.
- Event `timings` `{intent_ms, memory_ms, language_ms, answer_ms, gate_ms, history_ms, total_ms}` (khoá nào có tuỳ đường đi); event `no_evidence` `{reason: MODEL_REFUSED|NO_CHUNKS, retrieved, selected}`.
- Câu trả lời không còn thẻ `<source name>…</source name>`.

## Tự lập lại chỉ mục khi đổi embedding_version
- Backend phát hiện chỉ mục khác `embedding_version` hiện tại (lúc khởi động và lười khi có câu hỏi tài liệu) → lập lại trong nền theo từng nguồn (tăng dần, không xoá collection cũ).
- Trong lúc chạy, câu hỏi tài liệu trả `200`, `status=NO_EVIDENCE`, `answer` tiếng Việt từ `labels.vi.json` (`reindex.running`: "Đang cập nhật chỉ mục tài liệu (x/y), thử lại sau ít phút."), event `intent_routed.path="REINDEXING"`, event `reindex_progress {status,done,total,failed,started_at,finished_at,duration_s}` và trường `index` cùng nội dung. Không còn 503 `INDEX_INCOMPATIBLE` thô. Câu trả thẳng/HISTORY không bị chặn.
- `GET /api/index/status` (cần đăng nhập) trả trạng thái tiến độ: `idle|running|done|failed`.

## Hiển thị kết quả (BE, chỉ thêm khoá)
- Phản hồi `/api/chat` có thêm `grounding`: `"document"` (dựa tài liệu) hoặc `"none"` (phép tính, định nghĩa chung, follow-up từ lịch sử). Ghi chú "Không dựa trên tài liệu của bạn" đã bỏ khỏi `answer`; FE tự hiện nhãn theo `grounding`. Câu hỏi về nội dung tài liệu mà không có bằng chứng vẫn `NO_EVIDENCE` với thông báo chưa tìm thấy.
- `sources`: `[{n, doc_name, section, snippet, chunk_id}]` ở cấp trên của phản hồi (rỗng nếu không có). Thân `answer` dùng `[n]` thay cho mã chunk, dòng `Nguồn: [...]` không còn trong `answer`. `task_results[*].citations` và mọi khoá cũ giữ nguyên.
- `answer` không còn thẻ `<source name>`, `<src_…>`, mã chunk thô, hay tên tệp bị lặp.
- Chế độ Phân tích: mục "Tóm tắt" chỉ có khi thân bài >= 600 ký tự và có từ 2 miền trở lên (env `SYNTH_MIN_BODY_CHARS`, mặc định 600; 0 = luôn tóm tắt); không bao giờ lặp thân bài.
- Câu hỏi tổng quan kho ("trong tài liệu có gì", "có những tài liệu nào", "kho có gì"): `intent.intent="corpus_overview"`, `events[0].path="OVERVIEW"`, trả bằng mã từ danh sách tài liệu + tiêu đề mục, không gọi model, không đi chế độ Phân tích; kho trống nói không có tài liệu.

## Ngoại lệ FE nhỏ do Owner cho phép — tải nhiều tệp (branch s3/fe-sync)
Chỉ chạm `frontend/src/studio/components/LeftPanel.tsx` và `handleUpload` trong `frontend/src/studio/App.tsx`:
- Ô chọn tệp có `multiple`; kéo-thả nhận nhiều tệp và cả thư mục (khi trình duyệt có `webkitGetAsEntry`). Danh sách loại tệp giữ nguyên (`.pdf,.md,.markdown,.sql,.txt`); loại khác bị bỏ qua và báo rõ.
- Tải tối đa 2 tệp song song bằng `uploadDocument` có sẵn; hiện "Đang tải i/n…"; một tệp lỗi chỉ báo riêng tệp đó; cuối cùng "Đã tải x/y · lỗi: … · bỏ qua vì đã có: …". Tệp trùng tên đã có (hoặc trùng trong cùng lượt) bị bỏ qua và nói rõ.
- `handleUpload` nay trả `true/false` (không ném lỗi) và đếm số lượt đang tải để cờ `isUploading` không tắt sớm. `Workspace.onUploadFile` vẫn gọi được như cũ.

## Ngoại lệ FE thứ hai do Owner cho phép — chỉnh hiển thị (chỉ phần nhìn thấy, không đổi logic/contract)
File FE đã đổi:
- `frontend/src/studio/components/Workspace.tsx`: dòng chỉ số dưới câu trả lời (Clock + thời gian, Coins + token, FileText + số nguồn; "1 phút 3 giây" từ 60 giây trở lên, "8,4 giây" dưới 60; token "5,4k" kèm tooltip số đầy đủ vào/ra); nút "8 bước" có icon ListChecks, nút "Theo tác tử" đổi thành "Theo agent" (icon Users); thay hàng mã chunk cũ bằng `<SourceChips />`.
- `frontend/src/studio/components/SourceChips.tsx` (MỚI): chip theo tài liệu (FileText + tên file rút giữa giữ đuôi + "· N đoạn", kèm số [n]); tối đa 3 chip, còn lại "+N nguồn"; bấm chip mở khung đoạn trích ("[n] đoạn N · mục"). Không hiện mã chunk ở đâu cả. Lượt trả lời cũ chưa có `sources` thì lấy tên file qua `getChunk`.
- `frontend/src/studio/styles/studio-2026.css`: kiểu cho `.ws-meta`, `.cht-chip`, `.cht-src-pop`.
Ghi chú cho FE (BE đã đổi, chỉ thêm khoá):
- `sources[i]` có thêm `chunk_no` (số thứ tự đoạn trong tài liệu, bắt đầu từ 1) để hiện "đoạn N".
- Run lưu trong CSDL nay có `sources` và `grounding`, nên mở lại cuộc trò chuyện cũ vẫn ra đúng chip (`GET /api/runs/{id}`).
- Cụm "chunk [n]" / "đoạn [n]" trong `answer` đã bỏ ở BE, chỉ còn dấu [n].
- Chưa làm: bấm [n] trong thân câu trả lời để nhảy tới chip (vẫn là đề xuất #11).

## Guard chéo ngôn ngữ + bộ lọc nguồn B (BE, không đổi contract)
- `backend/app/chat/answer_guard.py` (`_number_check`, thêm `_check_figures`, `_looks_english`): bỏ điều kiện "mọi chunk khác ngôn ngữ với câu". Khi không có câu nguồn nào liên quan theo chủ ngữ, từng chunk khác ngôn ngữ được xét riêng; câu được giữ nếu có ít nhất một chunk mà số + đơn vị chuẩn hóa khớp ("100 yêu cầu mỗi phút" khớp "100 requests per minute"). Chunk cùng ngôn ngữ vẫn cần chủ ngữ liên quan; số sai (101, 13 characters, 60 mục) vẫn bị cắt.
- `backend/app/chat/source_filter.py` (MỚI) + `main.py`: sau guard chỉ giữ nguồn mà ít nhất một câu của câu trả lời giao cho người dùng khớp (đủ số của câu + từ khóa chung >=2, hoặc >=1 khi câu có số; từ khóa >=3 ký tự); nguồn đã được [n] trích trong thân luôn giữ; nếu lọc ra rỗng thì giữ nguyên danh sách gốc; [n] được đánh số lại. Khi có nguồn bị loại, `events` có `{"stage":"sources_filtered","before":[…],"after":[…],"dropped":[{n,doc_name,reason}]}`.
- Test mới trong `tests/test_display_wl.py`; test cũ không sửa.
