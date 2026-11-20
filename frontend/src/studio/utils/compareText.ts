// So sánh phiên bản (Đợt 4): nhãn tiếng Việt, xuất Markdown (Word) và CSV (mở bằng Excel) từ kết quả của máy chủ.
export type Change = 'ADDED' | 'MODIFIED' | 'REMOVED' | 'UNCHANGED' | 'MOVED' | 'MOVED_MODIFIED';
type Unit = { key: string; title: string; chapter?: string; body: string } | null;
type Item = { change: Change; old: Unit; new: Unit; clauses?: { clause: string; change: string; old?: string; new?: string }[]; numbers_changed?: string[] };

export const CHANGE_LABEL: Record<Change, string> = { ADDED: 'Thêm', MODIFIED: 'Sửa', REMOVED: 'Bỏ', UNCHANGED: 'Giữ', MOVED: 'Di chuyển', MOVED_MODIFIED: 'Di chuyển và sửa' };
export const changeTone = (c: Change) => (c === 'ADDED' ? 'ok' : c === 'REMOVED' ? 'bad' : c === 'UNCHANGED' ? 'mute' : c === 'MOVED' ? 'info' : 'warn');
const name = (u: Unit) => (u ? `${u.key}${u.title ? `. ${u.title}` : ''}` : '');
const CLAUSE: Record<string, string> = { ADDED: 'thêm', REMOVED: 'bỏ', MODIFIED: 'sửa' };

export function compareMarkdown(oldName: string, newName: string, items: Item[]): string {
  const lines = [`# So sánh phiên bản`, '', `Bản cũ: ${oldName}`, '', `Bản mới: ${newName}`, '',
    'Kết quả do mã đối chiếu theo Điều/Khoản, không do mô hình viết. Người có thẩm quyền xác nhận trước khi dùng.', '',
    '| Thay đổi | Bản cũ | Bản mới | Chi tiết |', '|---|---|---|---|'];
  for (const it of items) {
    const detail = (it.clauses ?? []).map(c => `Khoản ${c.clause} ${CLAUSE[c.change] ?? c.change}`).join('; ') || (it.numbers_changed?.length ? `Số: ${it.numbers_changed.join(', ')}` : '');
    lines.push(`| ${CHANGE_LABEL[it.change]} | ${name(it.old).replace(/\|/g, '/')} | ${name(it.new).replace(/\|/g, '/')} | ${detail.replace(/\|/g, '/')} |`);
  }
  return lines.join('\n');
}

const cell = (v: string) => `"${(v ?? '').replace(/"/g, '""').replace(/\r?\n/g, ' ')}"`;
/** CSV có BOM để Excel đọc đúng tiếng Việt. */
export function compareCsv(items: Item[]): string {
  const rows = [['Thay đổi', 'Mục bản cũ', 'Mục bản mới', 'Nội dung bản cũ', 'Nội dung bản mới', 'Khoản thay đổi', 'Số thay đổi']];
  for (const it of items) rows.push([CHANGE_LABEL[it.change], name(it.old), name(it.new), it.old?.body ?? '', it.new?.body ?? '',
    (it.clauses ?? []).map(c => `Khoản ${c.clause} ${CLAUSE[c.change] ?? c.change}`).join('; '), (it.numbers_changed ?? []).join(', ')]);
  return '﻿' + rows.map(r => r.map(cell).join(',')).join('\r\n');
}

/** Tách chữ theo từ để tô phần khác nhau giữa hai câu (LCS trên từ; câu ngắn nên đủ nhanh). */
export function wordDiff(a: string, b: string): { t: string; op: 'same' | 'del' | 'add' }[] {
  const x = a.split(/(\s+)/), y = b.split(/(\s+)/);
  if (x.length * y.length > 250000) return [{ t: a, op: 'del' }, { t: b, op: 'add' }];
  const dp = Array.from({ length: x.length + 1 }, () => new Uint16Array(y.length + 1));
  for (let i = x.length - 1; i >= 0; i--) for (let j = y.length - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { t: string; op: 'same' | 'del' | 'add' }[] = [];
  const push = (t: string, op: 'same' | 'del' | 'add') => { const l = out[out.length - 1]; if (l && l.op === op) l.t += t; else out.push({ t, op }); };
  let i = 0, j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { push(x[i], 'same'); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) push(x[i++], 'del'); else push(y[j++], 'add');
  }
  while (i < x.length) push(x[i++], 'del');
  while (j < y.length) push(y[j++], 'add');
  return out;
}
