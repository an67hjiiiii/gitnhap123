import test from 'node:test';
import assert from 'node:assert/strict';
import { inlineCites, citeLabel } from '../src/studio/utils/citations.ts';

const docs = [{ id: 'src_ab12', source_file: 'noi-quy-mau.txt' }];

test('nhãn đọc được', () => {
  assert.equal(citeLabel('src_ab12_c0004', docs), 'noi-quy-mau · đoạn 5');
  assert.equal(citeLabel('src_ff00_c0001', docs), 'ff00_c0001');
});

test('không lặp tên tài liệu khi mô hình đã viết tên tệp', () => {
  assert.equal(inlineCites('Theo noi-quy-mau.txt [src_ab12_c0000], thử việc 60 ngày.', docs), 'Theo noi-quy-mau.txt (đoạn 1), thử việc 60 ngày.');
  assert.equal(inlineCites('Theo noi-quy-mau (src_ab12_c0000).', docs), 'Theo noi-quy-mau (đoạn 1).');
});

test('một đoạn dẫn hai lần liền chỉ hiện một nhãn', () => {
  assert.equal(inlineCites('60 ngày [src_ab12_c0000][src_ab12_c0000].', docs), '60 ngày (noi-quy-mau · đoạn 1).');
  assert.equal(inlineCites('60 ngày [src_ab12_c0000], [src_ab12_c0000].', docs), '60 ngày (noi-quy-mau · đoạn 1).');
});

test('hai đoạn khác nhau vẫn giữ cả hai', () => {
  assert.equal(inlineCites('A [src_ab12_c0000] B [src_ab12_c0001]', docs), 'A (noi-quy-mau · đoạn 1) B (noi-quy-mau · đoạn 2)');
});

test('mã đoạn chép sai bị bỏ, không lộ chuỗi mã', () => {
  assert.equal(inlineCites('Tối đa 40 giờ (chunk_id: src_ab12: c0000).', docs), 'Tối đa 40 giờ.');
});
