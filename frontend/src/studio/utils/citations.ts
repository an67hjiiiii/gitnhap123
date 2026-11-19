// Nhãn trích dẫn đọc được thay cho mã đoạn "src_ab12_c0004".
export type CiteDoc = { id?: number | string; source_file: string };

const docTitle = (file: string) => file.replace(/\.[^.]+$/, '').replace(/_/g, ' ');

/** "src_ab12_c0004" → "Tên tài liệu · đoạn 5"; tài liệu ngoài không gian đang mở thì giữ mã rút gọn. */
export const citeLabel = (chunkId: string, docs: CiteDoc[]) => {
  const m = chunkId.match(/^(.*)_c(\d+)$/);
  const doc = m && docs.find(d => String(d.id) === m[1]);
  return doc ? `${docTitle(doc.source_file)} · đoạn ${Number(m![2]) + 1}` : chunkId.split('_').slice(-2).join('_');
};

const esc = (s: string) => s.replace(/[-.*+?^$(){}|[\]\\]/g, (c) => '\\' + c);

/** Mã đoạn chèn trong câu văn đổi thành nhãn; không lặp tên tài liệu (mô hình hay viết "tên.txt [mã]" hoặc dẫn một đoạn hai lần liền). */
export const inlineCites = (text: string, docs: CiteDoc[]) => {
  let out = text
    .replace(/(?:chunk(?:_id)?:?\s*)?\[?(src_[0-9a-f]+_c\d+)\]?/gi, (_, id: string) => `(${citeLabel(id, docs)})`)
    .replace(/\(\(([^()]*)\)\)/g, '($1)');
  // mã đoạn mô hình chép sai (không đổi được thành nhãn) thì bỏ; nút nguồn bên dưới vẫn còn
  out = out.replace(/\s*\((?:chunk(?:_id)?:?\s*)?src_[^()]*\)/gi, '');
  // cùng một nhãn đứng liền nhau → giữ một
  out = out.replace(/\(([^()]+)\)(?:[\s,;]*\(\1\))+/g, '($1)');
  // tên tài liệu vừa viết ngay trước nhãn → nhãn chỉ còn "đoạn N"
  for (const d of docs) {
    const title = docTitle(d.source_file);
    const before = `(?:${esc(d.source_file)}|${esc(title)})`;
    out = out.replace(new RegExp(`(${before}["”»]?)\\s*\\(${esc(title)} · (đoạn \\d+)\\)`, 'g'), '$1 ($2)');
  }
  return out;
};
