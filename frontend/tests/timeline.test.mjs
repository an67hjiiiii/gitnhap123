import test from 'node:test';
import assert from 'node:assert/strict';
import { buildTimeline, fmtMs } from '../src/studio/office3d/timeline.ts';

const at = (s) => new Date(Date.UTC(2026, 10, 23, 10, 0, 0) + s * 1000).toISOString();
// mốc thật lấy từ một lượt chạy 23/11 (câu nhiều việc, không có tài liệu)
const complex = [
  ['agent_selection', 0, { agents: ['business', 'general'] }], ['run_started', 0], ['product_request_routing', 0, { classification: 'COMPLEX_PROJECT_REQUEST' }],
  ['request_understanding', 0], ['knowledge_source_policy', 0, { has_documents: false, document_bound: false }],
  ['obligation_concern_extraction', 2.5], ['planning_retrieval', 2.5], ['planning_generation', 4.8], ['plan_verification', 4.8],
  ['planning_repair', 6.9], ['plan_verification', 6.9], ['decomposition', 6.9], ['adaptive_budget_plan', 6.9],
  ['task_started', 6.9, { task_id: 'T1', domain: 'business' }], ['task_retrieval', 6.9, { task_id: 'T1', domain: 'business' }],
  ['knowledge_source', 9.4, { task_id: 'T1', domain: 'business', source: 'general' }],
  ['task_completed', 9.4, { result: { task_id: 'T1', domain: 'business', status: 'COMPLETE' } }],
  ['synthesis_started', 9.4], ['run_finished', 13.5],
].map(([stage, s, extra]) => ({ stage, ts: at(s), ...(extra ?? {}) }));

test('dòng thời gian: đúng thứ tự người làm, thời gian lấy từ mốc thật', () => {
  const g = buildTimeline(complex);
  assert.deepEqual(g.map(x => x.who), ['Điều phối', 'Reviewer', 'Kinh doanh', 'Tổng hợp']);  // bước lặp lại (sửa kế hoạch, kiểm tra lần 2) gộp vào bước đã có
  const kd = g.find(x => x.who === 'Kinh doanh');
  assert.equal(kd.ms, 2500);                       // từ lúc nhận việc tới lúc xong
  assert.equal(g.at(-1).ms, 4100);                 // tổng hợp: từ synthesis_started tới run_finished
  assert.ok(g[0].steps.includes('Hiểu yêu cầu'));
  assert.equal(g.reduce((a, x) => a + x.ms, 0), 13500, 'tổng các bước bằng thời gian lượt chạy');
  assert.ok(!g.some(x => x.who === 'RAG'), 'không có tài liệu: RAG không xuất hiện');
});

test('câu đơn giản: thời gian viết thuộc Tổng hợp, không dồn vào bước tìm tài liệu', () => {
  const g = buildTimeline([
    { stage: 'agent_selection', ts: at(0) }, { stage: 'product_request_routing', classification: 'SIMPLE_PROJECT_QUESTION', ts: at(0) },
    { stage: 'knowledge_source_policy', has_documents: true, document_bound: true, ts: at(0) },
    { stage: 'vanilla_retrieval', ts: at(0.3) },
    { stage: 'knowledge_source', task_id: 'T1', domain: 'general', source: 'documents', ts: at(5.3) },
    { stage: 'run_finished', ts: at(5.4) },
  ]);
  assert.deepEqual(g.map(x => [x.who, x.ms]), [['Điều phối', 0], ['RAG', 300], ['Tổng hợp', 5100]]);
  assert.equal(g[1].eventIndex, 3);
});

test('thiếu mốc thời gian thì không ghi số; kế hoạch bị từ chối hiện lỗi', () => {
  const g = buildTimeline([{ stage: 'plan_verification' }, { stage: 'planning_rejected' }, { stage: 'run_failed' }]);
  assert.ok(g.every(x => x.ms === null));
  assert.equal(g.find(x => x.who === 'Reviewer').state, 'fail');
  assert.equal(fmtMs(null), '');
  assert.equal(fmtMs(2500), '2,5 giây');
  assert.equal(fmtMs(0), 'dưới 0,1 giây');
});

test('Reviewer trả bài: thời gian viết lại tính riêng cho bước "Viết lại theo góp ý"', () => {
  const g = buildTimeline([
    { stage: 'task_started', task_id: 'T1', domain: 'hr', ts: at(0) },
    { stage: 'task_completed', result: { task_id: 'T1', domain: 'hr', status: 'COMPLETE' }, ts: at(3) },
    { stage: 'synthesis_started', ts: at(3) },
    { stage: 'review_started', ts: at(6) },
    { stage: 'review_finished', review_status: 'ok', ts: at(8) },
    { stage: 'review_revision', unsupported: 1, ts: at(8) },
    { stage: 'synthesis_started', revision: true, ts: at(8) },
    { stage: 'run_finished', ts: at(12) },
  ]);
  assert.deepEqual(g.map(x => [x.who, x.ms]), [['Điều phối', 0], ['Nhân sự', 3000], ['Tổng hợp', 3000], ['Reviewer', 2000], ['Tổng hợp', 4000]]);
});
