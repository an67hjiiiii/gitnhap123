import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

// Đợt 7 (P2-1): mọi tệp trong bộ mẫu theo ngành phải có trong public/samples và ghi rõ là tài liệu mẫu.
test('bộ tài liệu mẫu theo ngành có đủ tệp', () => {
  const src = readFileSync(new URL('../src/studio/services/api.ts', import.meta.url), 'utf8');
  const block = src.slice(src.indexOf('export const SAMPLE_PACKS'), src.indexOf('export async function seedSampleDocs'));
  const files = [...block.matchAll(/'([\w/]+\.md)'/g)].map(m => m[1]);
  assert.ok(files.length >= 12);
  for (const f of files) {
    const path = new URL(`../public/samples/${f}`, import.meta.url);
    assert.ok(existsSync(path), f);
    if (f.startsWith('mau/')) assert.match(readFileSync(path, 'utf8'), /TÀI LIỆU MẪU/, f);
  }
});
