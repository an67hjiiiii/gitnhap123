# P-1: kết quả W-B
Các đường dẫn dưới đây tính từ gốc repo; không đổi bất kỳ token cap mặc định nào.
A thí nghiệm vanilla, không nguồn: `backend/app/evaluation/real_runner.py:362,461` gọi generate trực tiếp; cap `max(64, MAX_OUTPUT_TOKENS)`, mặc định 700 (`backend/app/providers/ollama.py:18,66,84`).
A trong ResearchPipeline là grounded RAG khác với A thí nghiệm: `backend/app/research/vanilla.py:54,58`; cùng cap MAX_OUTPUT_TOKENS, mặc định 700.
B0/B grounded thí nghiệm dùng chung một output `backend/app/evaluation/real_runner.py:430,443`; pipeline mặc định A, grounded schema và cap 700 như trên; C thí nghiệm tái dùng output, không chạy C nghiên cứu.
C nghiên cứu: extraction `backend/app/research/obligation_concern_extraction.py:303` không truyền cap riêng, mặc định 700.
Plan/repair: `backend/app/research/pipeline.py:415,491` truyền TASK_PLAN_MAX_OUTPUT_TOKENS; mặc định 700, tối thiểu 64 (`backend/app/core/config.py:32,50`; `backend/app/research/decomposer.py:774`).
Worker `backend/app/research/worker.py:39,43` và synthesize `backend/app/research/synthesizer.py:25`: MAX_OUTPUT_TOKENS, mặc định 700; B nghiên cứu cũng đi extraction/plan/worker/synthesize.
Ollama giữ think=False, format=schema và options.num_predict; done_reason=length hoặc JSON lỗi tại cap sinh OutputTruncatedError chứa partial_text, usage, output_limit, done_reason.
Planner bắt Exception (`backend/app/research/decomposer.py:814`); extraction được pipeline bọc (`backend/app/research/pipeline.py:351`); vanilla/worker/synthesize truyền lỗi lên handler FAILED (`backend/app/research/pipeline.py:686`); đã kiểm thử cả năm giai đoạn.
Đo bằng CountingFake và RunMetrics: A 1→1; C một task 4→4 = extraction+plan+worker+synthesize; so sánh bỏ qua/bật defensive citation filter, không phải benchmark Ollama.
C có n task thường n+3 calls; repair có thể thêm calls; không có evidence có thể bỏ worker hoặc A không gọi model.
Slot: số chữ Anh/Việt 0–100 được chuẩn hóa cả requirement và evidence; dấu chấm với đúng ba chữ số sau chấp nhận cả thập phân/lũy nghìn.
Giữ 30 ngày/tháng, 365 ngày/năm và decimal bytes; thêm alias 12 tháng/năm và binary KB/MB/GB, không suy diễn bắc cầu các cách đọc.
Đổi kỳ vọng chạy: test_vietnamese_thousands_dot_matches_plain_number 1 XFAIL→PASS; test_twelve_months_equal_one_year 1 XFAIL→PASS.
test_number_words_in_evidence_cover_digit_requirement 4 XFAIL→PASS; test_binary_size_equivalence 2 XFAIL→PASS; mọi assertion vẫn yêu cầu missing=[]; không sửa test_slot_check.py.
Giữ yếu điểm “Quản trị viên” chỉ lấy entity:quản; characterization hiện có chứng minh “quản lý” cũng khớp; không thêm heuristic. Hai xfail cũ về subject và tên đầu câu vẫn còn.
Citation helpers thuần: excerpt NFC/whitespace substring, quantity thiếu hỗ trợ, ID ngoài retrieved; excerpt filter duy nhất trong _evidence; numeric helper chỉ báo cáo, không đổi verdict.
## Khả thi cache verdict
Khuyến nghị CÓ cache có phiên bản; KHÔNG dùng nguyên bộ ba hash(requirement), hash(snapshot), config_hash hiện tại làm khóa đầy đủ.
Run đã lưu source_snapshot_id/config_hash (`backend/app/research/pipeline.py:216,217`); snapshot file-store hash toàn corpus (`backend/app/storage/source_store.py:176`), không riêng selected sources và không gồm mọi provenance/locator.
Retrieval lexical, slot/citation checks và verdict rules xác định khi input, thứ tự chunk, phiên bản code/cấu hình cố định; UUID, thời gian, event và model output không xác định.
LLM temperature mặc định 0.1 (`backend/app/providers/ollama.py:17`); model tag có thể đổi digest; digest chỉ nằm provenance (`backend/app/research/provenance.py:64`), không bảo đảm tái lập.
config_hash chỉ hash RuntimeConfig (`backend/app/core/config.py:70`), chưa bao gồm đủ condition/context_policy overrides, temperature, prompt/rule/code version, model digest, retrieval/index/embedding/tokenizer versions, nguồn được chọn, owner và conversation context.
Khóa đề nghị bổ sung các thành phần trên cùng snapshot nội dung+provenance/locator và effective_config; đổi requirement, ACL, nguồn/index/model/prompt/rules/config thì invalidation; cache hit vẫn kiểm tra quyền và ID nguồn.
Đặt cache qua repository có owner scope, trước pipeline từng requirement; hiện repository chỉ lưu findings/jobs (`backend/app/review/repository.py:18,26`), chưa có cache API; PG checkpoint (`backend/app/review_adapters/pg_repository.py:402`) hỗ trợ resume trong job, không phải cache liên job.
Giữ budget/cancellation/events và checkpoint của service/jobs (`backend/app/review/service.py:186,220`; `backend/app/review_adapters/durable_jobs.py:169`); tái tạo finding ID theo case/requirement mới, không replay event/ID cũ.
Hit tiết kiệm 1 call/requirement cho A có evidence, ≥4 cho C một task; thí nghiệm B0/B/C dùng chung grounded output chỉ tiết kiệm 1 call, không cộng ba lần.
Rủi ro: reuse lỗi/partial, nguồn đổi giữa hash và dùng, leak giữa owner, stale evidence/locator và config thiếu trường; chỉ cache kết quả thành công cùng evidence/provenance, kiểm tra lại snapshot, không cache FAILED/SKIPPED_BUDGET; chưa triển khai cache.
