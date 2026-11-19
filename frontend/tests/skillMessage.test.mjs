import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSkillMessage, summarizeSkill } from '../src/studio/utils/skillMessage.ts';

test('đọc lại thẻ đã lưu, kể cả ký tự > đã thoát', () => {
  const card = { skill: 'approver', label: 'Ai duyệt', reason: 'r', data: { approver: 'Giám đốc khối', rule: 'từ 5 ngày -> GĐ' } };
  const json = JSON.stringify(card).replace(/>/g, '\\u003e');
  const got = parseSkillMessage(`Kỹ năng Ai duyệt: người duyệt là Giám đốc khối.\n\n<!--skill-card:${json}-->`);
  assert.equal(got.summary, 'Kỹ năng Ai duyệt: người duyệt là Giám đốc khối.');
  assert.equal(got.card.data.rule, 'từ 5 ngày -> GĐ');
  assert.equal(parseSkillMessage('Câu trả lời thường'), null);
  assert.equal(parseSkillMessage('x <!--skill-card:{hỏng-->'), null);
});

test('tóm tắt một dòng', () => {
  assert.equal(summarizeSkill('approver', 'Ai duyệt', { approver: 'Giám đốc khối' }), 'Kỹ năng Ai duyệt: người duyệt là Giám đốc khối.');
  assert.equal(summarizeSkill('conditions', 'Kiểm tra điều kiện', { overall: 'NOT_ELIGIBLE', conditions: [{ condition: 'ĐTB từ 3,2', verdict: 'MET' }, { condition: 'Rèn luyện từ 70', verdict: 'NOT_MET' }] }),
    'Kỹ năng Kiểm tra điều kiện: Không đủ điều kiện (ĐTB từ 3,2: đạt; Rèn luyện từ 70: không đạt).');
});
