import test from 'node:test';
import assert from 'node:assert/strict';
import { stepState, stepView, skipReason } from '../src/studio/utils/stepExplain.ts';

const steps = [1, 2, 3, 4, 5, 6, 7, 8].map(n => ({ id: `step-${n}`, stepNumber: n, stages: {
  1: ['product_request_routing', 'request_understanding', 'obligation_concern_extraction'], 2: ['vanilla_retrieval', 'planning_retrieval'], 3: ['planning_generation', 'decomposition'],
  4: ['plan_verification', 'planning_repair', 'plan_anchoring', 'planning_rejected'], 5: ['normalization', 'validated_plan_handoff'], 6: ['adaptive_budget_plan', 'task_retrieval'],
  7: ['task_completed'], 8: ['run_finished'] }[n] }));
const noCode = (v) => assert.doesNotMatch(JSON.stringify(v), /SIMPLE_PROJECT_QUESTION|\bO\d\b|"T\d"/);

const simple = { condition: 'C', query: 'Bạn làm được gì?', events: [
  { stage: 'product_request_routing', classification: 'SIMPLE_PROJECT_QUESTION', detected_domains: [] },
  { stage: 'request_understanding', normalized_request: 'Bạn làm được gì?' },
  { stage: 'vanilla_retrieval', candidates: ['a', 'b', 'c'], selected: ['a'], dropped: [{ chunk_id: 'b' }] },
  { stage: 'run_finished', status: 'COMPLETE' }],
  task_results: [{ task_id: 'T1', domain: 'general', status: 'COMPLETE', answer: 'x', citations: ['a'] }] };

test('câu hỏi đơn giản: bước 1 có khối chọn đường, không lộ mã', () => {
  const v = stepView(simple, steps[0]);
  assert.equal(v.blocks[0].k, 'route');
  assert.equal(v.blocks[0].simple, true);
  assert.match(v.summary, /đường tắt/);
  noCode(v);
});

test('câu hỏi đơn giản: phễu tài liệu đúng số, bước 3 bỏ qua có lý do, bước 7 lấy từ task_results', () => {
  const f = stepView(simple, steps[1]).blocks.find(b => b.k === 'funnel');
  assert.deepEqual([f.found, f.used, f.dropped], [3, 1, 1]);
  assert.equal(stepState(simple, steps[2]), 'skip');
  assert.match(skipReason(simple, steps[2], steps), /đơn giản/);
  assert.equal(stepState(simple, steps[6]), 'done');
  assert.equal(stepView(simple, steps[6]).blocks[0].items.length, 1);
});

test('kế hoạch bị từ chối: bước 4 dừng, đối chiếu nghĩa vụ bằng mô tả, bước sau nói đã dừng ở bước 4', () => {
  const raw = { condition: 'C', events: [
    { stage: 'obligation_concern_extraction', obligations: [{ obligation_id: 'O1', description: 'Nêu thời hạn' }, { obligation_id: 'O2', description: 'Nêu người duyệt' }], concerns: [] },
    { stage: 'decomposition', tasks: [{ task_id: 'T1', domain: 'conditions', goal: 'g' }] },
    { stage: 'plan_verification', phase: 'initial', valid: false, covered_obligations: ['O1'], missing_required_obligations: ['O2'] },
    { stage: 'planning_rejected', reason: 'task_plan_verification_failed' }] };
  assert.equal(stepState(raw, steps[3]), 'stop');
  const v = stepView(raw, steps[3]);
  const check = v.blocks.find(b => b.k === 'checklist');
  assert.deepEqual(check.items, [{ text: 'Nêu thời hạn', ok: true }, { text: 'Nêu người duyệt', ok: false }]);
  noCode(v);
  assert.match(skipReason(raw, steps[4], steps), /bước 4/);
});
