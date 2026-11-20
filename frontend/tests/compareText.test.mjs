import test from 'node:test';
import assert from 'node:assert/strict';
import { compareMarkdown, compareCsv, wordDiff, CHANGE_LABEL } from '../src/studio/utils/compareText.ts';

const items = [
  { change: 'MODIFIED', old: { key: 'Điều 4', title: 'Nghỉ phép năm', body: 'được nghỉ 12 ngày' }, new: { key: 'Điều 4', title: 'Nghỉ phép năm', body: 'được nghỉ 14 ngày' },
    clauses: [{ clause: '1', change: 'MODIFIED' }, { clause: '4', change: 'ADDED' }], numbers_changed: ['12', '14'] },
  { change: 'ADDED', old: null, new: { key: 'Điều 6', title: 'Làm việc từ xa', body: 'tối đa 2 ngày' } },
  { change: 'REMOVED', old: { key: 'Điều 7', title: 'Khen | thưởng', body: 'thưởng "cuối năm"' }, new: null },
];

test('Markdown so sánh có bảng và ghi rõ do mã đối chiếu', () => {
  const md = compareMarkdown('Quy chế 2024', 'Quy chế 2026', items);
  assert.match(md, /\| Sửa \| Điều 4\. Nghỉ phép năm \| Điều 4\. Nghỉ phép năm \| Khoản 1 sửa; Khoản 4 thêm \|/);
  assert.match(md, /không do mô hình viết/);
  assert.ok(!md.includes('Khen | thưởng'));  // dấu | trong tiêu đề không làm vỡ bảng
});

test('CSV có BOM, thoát dấu ngoặc kép', () => {
  const csv = compareCsv(items);
  assert.ok(csv.startsWith('﻿'));
  assert.match(csv, /"thưởng ""cuối năm"""/);
  assert.equal(csv.split('\r\n').length, 4);
  assert.equal(CHANGE_LABEL.MOVED_MODIFIED, 'Di chuyển và sửa');
});

test('tô khác biệt theo từ', () => {
  const d = wordDiff('được nghỉ 12 ngày', 'được nghỉ 14 ngày');
  assert.deepEqual(d.filter(p => p.op !== 'same').map(p => [p.op, p.t]), [['del', '12'], ['add', '14']]);
  assert.equal(d.filter(p => p.op !== 'add').map(p => p.t).join(''), 'được nghỉ 12 ngày');
});
