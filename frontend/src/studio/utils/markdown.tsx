import React from 'react';

// Hiển thị markdown đơn giản từ đầu ra mô hình thành phần tử React (không dùng HTML thô, nên không có rủi ro chèn mã).
// shortcut: chỉ hỗ trợ tiêu đề, đậm/nghiêng, mã, danh sách, bảng, đường kẻ; cần đầy đủ CommonMark thì dùng thư viện chuyên dụng.
function inline(text: string, key: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith('**')) out.push(<strong key={`${key}-${i++}`}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith('`')) out.push(<code key={`${key}-${i++}`}>{t.slice(1, -1)}</code>);
    else out.push(<em key={`${key}-${i++}`}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const cells = (row: string) => row.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, '').split('\n');
  const blocks: React.ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const k = `b${i}`;
    if (!line.trim()) { i++; continue; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { const Tag = (['h3', 'h3', 'h4', 'h5'] as const)[h[1].length - 1]; blocks.push(<Tag key={k}>{inline(h[2].replace(/\*\*/g, ''), k)}</Tag>); i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { blocks.push(<hr key={k} />); i++; continue; }
    if (/^\s*\|/.test(line)) {
      const rows: string[] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const body = rows.filter(r => !/^\s*\|?\s*:?-{2,}/.test(r));
      const [head, ...rest] = body;
      blocks.push(<div className="md-table" key={k}><table>
        {head && <thead><tr>{cells(head).map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>}
        <tbody>{rest.map((r, ri) => <tr key={ri}>{cells(r).map((c, j) => <td key={j}>{inline(c, `${k}r${ri}c${j}`)}</td>)}</tr>)}</tbody>
      </table></div>);
      continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*+]|\d+[.)])\s+/, ''));
      const List = ordered ? 'ol' : 'ul';
      blocks.push(<List key={k}>{items.map((it, j) => <li key={j}>{inline(it, `${k}l${j}`)}</li>)}</List>);
      continue;
    }
    if (/^```/.test(line)) {
      const code: string[] = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
      i++;
      blocks.push(<pre key={k} className="md-code">{code.join('\n')}</pre>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*\||\s*([-*+]|\d+[.)])\s+|```|\s*-{3,}\s*$)/.test(lines[i])) para.push(lines[i++]);
    if (!para.length) { para.push(lines[i++]); }
    blocks.push(<p key={k}>{inline(para.join(' '), k)}</p>);
  }
  return <div className="md">{blocks}</div>;
}
