import test from 'node:test';
import assert from 'node:assert/strict';
import { progressLabel } from '../src/studio/utils/progress.ts';

test('nhãn tiến trình tiếng Việt', () => {
  assert.equal(progressLabel({ stage: 'product_request_routing', classification: 'SIMPLE_PROJECT_QUESTION' }), 'Câu hỏi một ý: tìm trong tài liệu để trả lời thẳng');
  assert.equal(progressLabel({ stage: 'product_request_routing', classification: 'COMPLEX_PROJECT_REQUEST' }), 'Yêu cầu nhiều ý: chia việc cho các tác tử');
  assert.equal(progressLabel({ stage: 'task_retrieval', task_id: 'T2' }), 'Nhiệm vụ 2: đang đọc tài liệu');
  assert.equal(progressLabel({ stage: 'task_completed', task_id: 'task_3' }), 'Nhiệm vụ 3: xong');
  assert.equal(progressLabel({ stage: 'agent_selection', agents: ['terms', 'procedure', 'general'] }), 'Chọn tác tử: Điều khoản, Quy trình, Tổng hợp');
  assert.equal(progressLabel({ stage: 'run_started' }), null);
  assert.equal(progressLabel({ stage: 'lifecycle_transition' }), null);
});
