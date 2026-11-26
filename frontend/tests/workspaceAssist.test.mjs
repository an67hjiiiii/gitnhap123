import test from 'node:test';
import assert from 'node:assert/strict';
import { suggestSkills, traceOf, keyTerms, highlightParts } from '../src/studio/utils/workspaceAssist.ts';

test('kỹ năng đề xuất theo loại tài liệu và câu hỏi', () => {
  assert.deepEqual(suggestSkills([]).map(s => s.key), []);
  assert.deepEqual(suggestSkills(['contract']).map(s => s.key), ['contract_review']);
  assert.deepEqual(suggestSkills(['regulation']).map(s => s.key), ['validity', 'conditions']);
  assert.equal(suggestSkills([], 'Ai duyệt đơn nghỉ phép?')[0].key, 'approver');
  assert.equal(suggestSkills([], 'Quy trình xử lý sự cố gồm các bước nào')[0].key, 'procedure');
  assert.ok(suggestSkills(['contract', 'regulation', 'internal_rules'], 'điều kiện quy trình ai duyệt').length <= 3);
});

test('quá trình xử lý lấy từ sự kiện thật, không bịa số', () => {
  assert.equal(traceOf(null), null);
  const t = traceOf({ status: 'COMPLETE', events: [{ stage: 'product_request_routing', classification: 'SIMPLE_PROJECT_QUESTION' }, { stage: 'vanilla_retrieval' }, { stage: 'vanilla_retrieval' }, { stage: 'run_started' }],
    task_results: [{ domain: 'procedure' }, { domain: 'procedure' }], metrics: { input_tokens: 100, output_tokens: 20, latency_ms: 3000 } });
  assert.deepEqual(t.steps, ['Câu hỏi một ý: tìm trong tài liệu để trả lời thẳng', 'Đã tìm đoạn liên quan, đang viết câu trả lời']);
  assert.deepEqual(t.agents, ['procedure']);
  assert.equal(t.tokens, 120);
  assert.equal(traceOf({ events: [] }).tokens, null);  // chưa đo → null
});

test('tô từ khóa không phân biệt dấu', () => {
  const terms = keyTerms('CSDL gồm những bảng nào?');
  assert.deepEqual(terms, ['csdl', 'bang']);
  const parts = highlightParts('Danh sách bảng chính của CSDL', terms);
  assert.deepEqual(parts.filter(p => p.hit).map(p => p.t), ['bảng', 'CSDL']);
  assert.equal(parts.map(p => p.t).join(''), 'Danh sách bảng chính của CSDL');
});

test('tô cụm từ ghép V12: hỏi Lợi nhuận KHÔNG tô nhầm chữ LỢI trong PHÚC LỢI', () => {
  const terms = keyTerms('Tổng doanh thu thuần và lợi nhuận trước thuế Quý IV/2025 là bao nhiêu? Chính sách bảo hiểm sức khỏe?');
  assert.ok(terms.includes('loi nhuan'), `Phải giữ cụm ghép 'loi nhuan', nhận được: ${terms.join(', ')}`);
  assert.ok(!terms.includes('loi'), `Không tách lẻ tiếng đơn 'loi' gây tô nhầm PHÚC LỢI: ${terms.join(', ')}`);

  const wrongHit = highlightParts('QUY CHẾ NHÂN SỰ, CHẤM CÔNG & PHÚC LỢI VIETCORE AI', terms);
  assert.ok(!wrongHit.some(p => p.hit && /lợi/i.test(p.t)), 'Tuyệt đối không tô nhầm chữ LỢI trong PHÚC LỢI');

  const rightHit = highlightParts('Tổng doanh thu thuần đạt 18.000 triệu VNĐ và lợi nhuận trước thuế 6.000 triệu VNĐ.', terms);
  const hitTexts = rightHit.filter(p => p.hit).map(p => p.t.toLowerCase());
  assert.ok(hitTexts.some(t => t.includes('lợi nhuận')), `Phải tô đúng cụm 'lợi nhuận', nhận được: ${hitTexts.join(', ')}`);
  assert.ok(hitTexts.some(t => t.includes('doanh thu')), `Phải tô đúng cụm 'doanh thu', nhận được: ${hitTexts.join(', ')}`);
});
