// Kết quả đã lưu (đợt 6, mục 2b): mở lại những gì AI đã làm (hồ sơ tài liệu, mâu thuẫn, gói thiết kế, đánh giá…).
// Báo cáo lưu ở backend (/studio/reports) theo từng người; mở = đi tới công cụ đã tạo ra nó (công cụ tự nạp bản đã lưu).
import React, { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Archive, FileStack, RefreshCw, Trash2 } from 'lucide-react';
import { deleteReport, listAllReports, SavedReport } from '../services/api';
import type { NavigationTab } from '../types';
import { ToolHeader } from './analysis/shared';
import '../styles/pages-2b.css';

// loại báo cáo → tên hiển thị và trang công cụ mở lại được
const KINDS: Record<string, { label: string; tab?: NavigationTab }> = {
  doc_profile: { label: 'Hồ sơ tài liệu', tab: 'documents' },
  mindmap: { label: 'Sơ đồ tư duy', tab: 'documents' },
  consistency: { label: 'Kiểm tra mâu thuẫn', tab: 'consistency' },
  evaluation: { label: 'Phòng đánh giá', tab: 'evaluation' },
  eval_set: { label: 'Bộ câu hỏi đánh giá', tab: 'evaluation' },
  design: { label: 'Gói thiết kế', tab: 'toolkit' },
  req_quality: { label: 'Chất lượng yêu cầu', tab: 'toolkit' },
  security_review: { label: 'Rà soát bảo mật', tab: 'toolkit' },
  traceability: { label: 'Rà soát theo tiêu chí', tab: 'toolkit' },
  criteria: { label: 'Danh mục tiêu chí', tab: 'toolkit' },
};

export const SavedResultsView: React.FC<{ onOpen: (tab: NavigationTab) => void }> = ({ onOpen }) => {
  const [rows, setRows] = useState<SavedReport[] | null>(null);
  const [kind, setKind] = useState('');
  const [error, setError] = useState('');
  const load = () => { setError(''); listAllReports().then(setRows).catch(e => setError(e.message)); };
  useEffect(load, []);
  const kinds = useMemo(() => [...new Set((rows ?? []).map(r => r.kind))], [rows]);
  const shown = (rows ?? []).filter(r => !kind || r.kind === kind);
  const remove = async (r: SavedReport) => {
    if (!confirm(`Xóa kết quả đã lưu “${r.title}”? Không hoàn tác được.`)) return;
    try { await deleteReport(r.report_id); setRows(v => (v ?? []).filter(x => x.report_id !== r.report_id)); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <main className="pg tl tone-overview sav">
      <div className="pg-col">
        <ToolHeader Icon={Archive} title="Kết quả đã lưu" desc="Những gì AI đã làm và bạn đã lưu: hồ sơ tài liệu, kiểm tra mâu thuẫn, gói thiết kế, đánh giá. Mở lại để xem, sửa hoặc xuất."
          right={<button className="btn btn-ghost" onClick={load} aria-label="Tải lại"><RefreshCw size={15} />Tải lại</button>} />
        {kinds.length > 1 && <nav className="sav-kinds" aria-label="Lọc theo loại">
          <button type="button" className={!kind ? 'is-on' : ''} aria-pressed={!kind} onClick={() => setKind('')}>Tất cả <em>{rows?.length ?? 0}</em></button>
          {kinds.map(k => <button key={k} type="button" className={kind === k ? 'is-on' : ''} aria-pressed={kind === k} onClick={() => setKind(k)}>
            {KINDS[k]?.label ?? k} <em>{(rows ?? []).filter(r => r.kind === k).length}</em></button>)}
        </nav>}
        {error && <p className="note is-error" role="alert">{error}</p>}
        {rows === null && !error && <p className="lib-empty">Đang tải…</p>}
        {rows && rows.length === 0 && <section className="dz-card sav-empty"><FileStack size={28} /><b>Chưa có kết quả nào được lưu</b>
          <p>Khi lập hồ sơ tài liệu, kiểm tra mâu thuẫn hay chạy đánh giá, bấm “Lưu” để giữ lại ở đây. Thẻ kết quả của kỹ năng trong chat được giữ trong cuộc trò chuyện.</p></section>}
        {shown.length > 0 && <ul className="sav-grid">{shown.map(r => {
          const k = KINDS[r.kind];
          return <li key={r.report_id} className="dz-card sav-card">
            <span className="sav-kind">{k?.label ?? r.kind}</span>
            <b className="sav-title">{r.title}</b>
            <small>{new Date(r.updated_at ?? r.created_at).toLocaleString('vi-VN')}</small>
            <span className="sav-acts">
              {k?.tab && <button type="button" className="btn btn-dark is-sm" onClick={() => onOpen(k.tab!)}><ArrowUpRight size={14} />Mở</button>}
              <button type="button" className="btn btn-ghost is-sm" onClick={() => remove(r)} aria-label={`Xóa ${r.title}`}><Trash2 size={14} /></button>
            </span>
          </li>;
        })}</ul>}
      </div>
    </main>
  );
};
