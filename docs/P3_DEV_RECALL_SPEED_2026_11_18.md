# P3 DEV recall / speed countercheck — 18/11/2026

## Scope and result
Canonical bge2:21 files/1277 chunks; DEV29/TEST81 split unchanged. Only scratch vtest_full_bge2:55440 was used. No dev DB/8000/5173, source mutation, deletion, cloud inference or TEST access. Generation remains local Qwen, serial. This is measurement evidence, not semantic acceptance.

**DECISION: DEV_SPEED_PARTIAL_EXPORT_BLOCKED.** D3-k6 was provisionally chosen for DEV review among tied coverage arms, not as a statistically superior method. It cannot be finalized for CSV: two full-DEV prompts exceed the required8192 context. No further fix or retry was attempted. The old CSV remains historical context4_v4, not an approved current configuration.

## D0 control and why14/34 cannot be compared directly with31/34
Historical D0 API `/api/studio/retrieval-test` calls `_retrieve_candidates(min_score=0)` and never executes product BM25 fusion, despite the environment flag. The desired old-BM25+nomic algorithm is therefore probed separately via actual `product_retrieve`. Both use fresh nomic embeddings of the same canonical1277 chunks and precomputed DEV queries; no old index is overwritten.

| Canonical corpus, new metric | @5 | @10 | @20 | elapsed29 queries(s) |
|---|---:|---:|---:|---:|
| Historical API, filteroff | 6/34 | 8/34 | 13/34 | 5.66 |
| Historical API, filteron | 6/34 | 10/34 | 15/34 | 7.29 |
| Actual old-BM25+nomic hybrid, off | 25/34 | 28/34 | 30/34 | 41.38 |
| Actual old-BM25+nomic hybrid, on | 28/34 | 29/34 | 31/34 | 105.24 |

n=34 unique gold source/article pairs in27 gold-bearing DEV questions;29 queries total. Embedding preparation81.71s,1277 chunks/32 queries is outside recall timing. Filteron also activates VERSION_RELATIONS; do not call it a single-flag causal effect. The slow105.24s is retained, not hidden.

On the SAME saved current BM25 ranking, changing only raw filename matching to unique PDF/TXT-stem alias changes @10 from4/34 to31/34. On the SAME nomic hybrid/on ranking, alias+first-body-article gives19/34, alias+structural-heading article gives29/34. These are scoring-only controls, not retrieval improvements. Historical14/34 used a different corpus representation (report:21/1282), endpoint, inherited flags and matcher. Separate causal contributions of corpus re-ingestion or expanded chunks remain **CHƯA KIỂM CHỨNG**. No claim of algorithmic14→31 improvement is justified.

## Paired speed control
Same10 independent DEV questions, one observation/case/arm; ordinary7 questions, six with7 gold pairs; three synthetic version-diff routes are N/A for the ordinary canonical-article gold matcher. All40 paired records valid,36 actual generation calls. Actual Ollama context8192 throughout; ps26%CPU/74%GPU. Ordinary evidence budget3000, output700; synthetic diff bypasses that ordinary budget and is reported separately. Actual paired prompt counts1098–7340 tokens, n36 calls. No sampling/model change.

| Arm(n10 each) | mean sec/case | median sec/case | prompt gold pairs(n7,n6 cases) | missing exact number/date atoms(n18,n8 cases) |
|---|---:|---:|---:|---:|
| bm25_k5 | 25.92 | 24.29 | 5/7 | 12/18 |
| bm25_k6 | 138.21 | 22.63 | 5/7 | 12/18 |
| d3_k5 | 25.71 | 23.57 | 5/7 | 12/18 |
| d3_k6 | 23.78 | 24.39 | 5/7 | 10/18 |

Each arm has at least one gold in5/6 assessable cases. Context4_v4 top-k10 had6/7 unique pairs on the same six cases; smaller k retains5/7. This is finite prompt coverage, not a semantic score. Speed target<=16s/case is not demonstrated. BM25k6/L1_6=1189.64s (1187.25s within provider), cause unverified; all primary statistics retain it. Other differences are too uncertain for a superiority claim at one observation/case. Windows power-log access did not establish a pause; no sleep/runtime cause is asserted.

## Full candidate and CSV gate
Full D3-k6 used10 existing sample records and only19 remaining DEV pipeline executions.29 terminal records: {'COMPLETE': 19, 'PARTIAL': 6, 'NO_EVIDENCE': 4}. There were24 actual model generations and two preflight blocks; three cases had no generation by normal routing. L2_62 and L2_64 match prior serialized system/user/evidence exactly, with known measured8516 and8531 input tokens. Both exceed8192 even before700 output; guard prevented new calls and silent truncation. No answer was fabricated from these blocks. CSV was NOT re-exported. Original CSV hash remains `e4896509f3ef3b5df2a35c1422f7133d8be4df8060c40ea4fa00fbe25817a45e`.

The provisional choice was therefore not finalized. Fixing only the measurement estimate was justified for L2_61: exact7340+700=8040 fits8192, confirmed live. The earlier blocked attempt and9 valid reused records remain mapped in `bm25_k5/reuse_mapping.json`; no valid generation was repeated. That instrumentation correction does not justify relaxing the guard for8516/8531.

## Seven prior NO_EVIDENCE cases
- L1_48: scholarship amount is absent from all60 stored chunks of the requested TT40 source; no claim about unrelated sources or legal completeness.
- L1_41,L2_54,L2_55: version_diffs routing returned no chunks despite article evidence in canonical retrieval.
- L2_61,L2_62,L2_64: wrong-family diff context displaced available TT34 article evidence. Model refusal is downstream, not proof of corpus absence or model deficiency.
- TT40/83 are unverified because their source templates omit document number, issue date and effective date. They contain body text; no dates were invented.

## Provenance / limitations
External evidence directory: `D:/CAP1-Orchestration/work/p3/speed5_verified`; D0 and absence audit: sibling `speed5`. Per-arm manifests carry app/config/data/model/DEV/gold/runner hashes; artifact_hashes.json enumerates file hashes. Code app hash `4bfb3f3c4853e9387713fb848c496bec6a61e5d9e4731bddffe95e2312ec9282`; data hash `8ea644f600483c1ecc419dbf48e9b1fbc3a9314ab682c86ab336c47e6eafa80b`. Scripts are dated scratch experiments; D0 consumes the preserved preparation cache/snapshot in speed5/d0, not an arbitrary new corpus.

Focused offline tests:7 passed. No broad suite or TEST run. Production semantics were not changed by this task; prior optional num_ctx provider support remains as previously reviewed. Work stays on p3/combo; no main/force. Human semantic correctness is pending. Required next decision is whether to authorize a general version-diff intent/budget fix or revise the speed/context tradeoff; no per-question patch is proposed.
