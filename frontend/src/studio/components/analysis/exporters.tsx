// Xuất báo cáo: Word (.docx do backend dựng bằng thư viện chuẩn), PDF (hộp thoại in của trình duyệt → Lưu thành PDF), Markdown.
import React, { useState } from 'react';
import { Download, FileText, Printer } from 'lucide-react';
import { exportDocx } from '../../services/api';
import { download } from './shared';

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const inline = (s: string) => esc(s)
  .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*([^*\s][^*]*)\*/g, '<i>$1</i>');

/** Markdown đơn giản (đề mục, đoạn, danh sách, bảng, đậm/nghiêng/mã) thành HTML đã thoát ký tự, chỉ dùng cho bản in. */
export function mdToHtml(md: string): string {
  const out: string[] = [];
  let list: 'ul' | 'ol' | null = null, para: string[] = [], table: string[][] = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const flushTable = () => {
    if (table.length) out.push(`<table>${table.map((r, i) => `<tr>${r.map(c => i ? `<td>${inline(c)}</td>` : `<th>${inline(c)}</th>`).join('')}</tr>`).join('')}</table>`);
    table = [];
  };
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trim();
    let m: RegExpMatchArray | null;
    if (/^\|.*\|$/.test(line)) {
      flushPara(); flushList();
      const cells = line.slice(1, -1).split('|').map(c => c.trim());
      if (!cells.every(c => !c || /^:?-{2,}:?$/.test(c))) table.push(cells);
      continue;
    }
    flushTable();
    if (!line || /^(-{3,}|\*{3,})$/.test(line)) { flushPara(); flushList(); if (line) out.push('<hr>'); }
    else if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { flushPara(); flushList(); const l = Math.min(m[1].length, 4); out.push(`<h${l}>${inline(m[2])}</h${l}>`); }
    else if ((m = line.match(/^[-*+]\s+(.*)$/))) { flushPara(); if (list !== 'ul') { flushList(); out.push('<ul>'); list = 'ul'; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = line.match(/^\d+[.)]\s+(.*)$/))) { flushPara(); if (list !== 'ol') { flushList(); out.push('<ol>'); list = 'ol'; } out.push(`<li>${inline(m[1])}</li>`); }
    else { flushList(); para.push(line); }
  }
  flushPara(); flushList(); flushTable();
  return out.join('\n');
}

const PRINT_CSS = `@page{size:A4;margin:18mm 16mm}body{font:11pt/1.55 "Segoe UI",Arial,sans-serif;color:#1f2933;max-width:760px;margin:24px auto;padding:0 16px}
h1{font-size:20pt;color:#0e5e6f;margin:0 0 12px}h2{font-size:14pt;color:#0e5e6f;margin:20px 0 8px;border-bottom:1px solid #d5dde6;padding-bottom:4px}
h3,h4{font-size:12pt;margin:16px 0 6px}p,li{margin:0 0 6px}table{border-collapse:collapse;width:100%;margin:8px 0 12px}
th,td{border:1px solid #bfc5cc;padding:5px 8px;text-align:left;vertical-align:top}th{background:#eef1f4}code{font-family:Consolas,monospace;background:#f1f3f5;padding:0 3px}
hr{border:0;border-top:1px solid #d5dde6;margin:18px 0}h2,h3{break-after:avoid}tr,li{break-inside:avoid}`;

/** Mở bản in trong cửa sổ mới; người dùng chọn "Lưu thành PDF" trong hộp thoại in. */
export function printPdf(title: string, markdown: string) {
  const w = window.open('', '_blank', 'width=900,height=1100');
  if (!w) throw new Error('Trình duyệt đã chặn cửa sổ in. Hãy cho phép cửa sổ bật lên rồi thử lại.');
  w.document.write(`<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>${esc(title)}</title><style>${PRINT_CSS}</style></head><body>${mdToHtml(markdown)}</body></html>`);
  w.document.close();
  w.focus();
  window.setTimeout(() => w.print(), 300);
}

export function saveBlob(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Ba nút tải: Word, PDF, Markdown. */
export function ExportButtons({ title, markdown, filename }: { title: string; markdown: string; filename: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const word = async () => {
    setBusy(true); setError(null);
    try { saveBlob(`${filename}.docx`, await exportDocx(markdown)); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const pdf = () => { setError(null); try { printPdf(title, markdown); } catch (e: any) { setError(e.message); } };
  return <span className="xp" role="group" aria-label="Tải xuống">
    <button type="button" className="btn btn-ghost is-sm" onClick={word} disabled={busy}>{busy ? <span className="spin is-dark" /> : <FileText size={14} />}Word</button>
    <button type="button" className="btn btn-ghost is-sm" onClick={pdf} title="Mở hộp thoại in, chọn Lưu thành PDF"><Printer size={14} />PDF</button>
    <button type="button" className="btn btn-ghost is-sm" onClick={() => download(`${filename}.md`, markdown, 'text/markdown')}><Download size={14} />.md</button>
    {error && <span className="af-err" role="alert">{error}</span>}
  </span>;
}
