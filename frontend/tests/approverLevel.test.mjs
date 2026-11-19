import test from 'node:test';
import assert from 'node:assert/strict';
import { suggestLevel } from '../src/studio/utils/approverLevel.ts';

test('gợi ý cấp duyệt từ tên người duyệt', () => {
  assert.equal(suggestLevel('Giám đốc khối'), 'EXECUTIVE');
  assert.equal(suggestLevel('Hiệu trưởng'), 'EXECUTIVE');
  assert.equal(suggestLevel('Trưởng phòng'), 'MANAGER');
  assert.equal(suggestLevel('Trưởng khoa'), 'MANAGER');
  assert.equal(suggestLevel('Kế toán viên'), null);
  assert.equal(suggestLevel(''), null);
});
