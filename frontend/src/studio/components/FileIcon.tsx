// Biểu tượng tệp theo định dạng, dùng chung mọi nơi hiện tài liệu (21/11): trang giấy gập góc + ô chữ màu,
// kiểu biểu tượng tệp quen thuộc của bộ văn phòng (Word xanh W, Excel xanh lá X, PowerPoint cam P, PDF đỏ).
import React from 'react';

const KIND: Record<string, { c: string; t: string }> = {
  doc: { c: '#185abd', t: 'W' }, docx: { c: '#185abd', t: 'W' },
  xls: { c: '#107c41', t: 'X' }, xlsx: { c: '#107c41', t: 'X' }, csv: { c: '#107c41', t: 'X' },
  ppt: { c: '#c43e1c', t: 'P' }, pptx: { c: '#c43e1c', t: 'P' },
  pdf: { c: '#e2231a', t: 'PDF' }, md: { c: '#334155', t: 'MD' }, markdown: { c: '#334155', t: 'MD' },
  txt: { c: '#64748b', t: 'TXT' }, sql: { c: '#0e7490', t: 'SQL' },
  png: { c: '#7c3aed', t: 'IMG' }, jpg: { c: '#7c3aed', t: 'IMG' }, jpeg: { c: '#7c3aed', t: 'IMG' }, tif: { c: '#7c3aed', t: 'IMG' }, tiff: { c: '#7c3aed', t: 'IMG' },
};
export const extOf = (f: string) => (f.match(/\.([a-z0-9]+)$/i)?.[1] ?? '').toLowerCase();

export function FileIcon({ name, size = 32, className = '' }: { name: string; size?: number; className?: string }) {
  const k = KIND[extOf(name)] ?? { c: '#64748b', t: 'TL' };
  const wide = k.t.length > 1;
  return <svg className={`file-ico ${className}`.trim()} viewBox="0 0 36 40" width={size} height={size * 40 / 36} aria-hidden="true">
    <path d="M9 1.5h15.5L33 10v26a2.5 2.5 0 0 1-2.5 2.5H9A2.5 2.5 0 0 1 6.5 36V4A2.5 2.5 0 0 1 9 1.5z" fill="#fff" stroke="rgba(15,27,43,.18)" />
    <path d="M24.5 1.5V8a2 2 0 0 0 2 2H33" fill="#eef2f7" stroke="rgba(15,27,43,.18)" />
    <path d="M13 16h14M13 20.5h14M13 25h10" stroke={k.c} strokeOpacity=".28" strokeWidth="1.6" strokeLinecap="round" />
    <rect x="0.5" y={wide ? 22 : 18} width={wide ? 25 : 19} height={wide ? 13 : 17} rx="3.5" fill={k.c} />
    <text x={wide ? 13 : 10} y={wide ? 31.6 : 30.5} textAnchor="middle" fill="#fff" fontSize={wide ? 8.6 : 12.5} fontWeight="800" fontFamily="Inter, Segoe UI, Arial, sans-serif">{k.t}</text>
  </svg>;
}
