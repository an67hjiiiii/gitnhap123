// Nhật ký kiểm toán: thao tác của mọi tài khoản (ai, làm gì, trên đối tượng nào, kết quả), mới nhất trước; tìm kiếm, lọc lỗi, phân trang.
import React, { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, Download, Search, ShieldAlert } from 'lucide-react';
import { AuditRow, getAdminAudit } from '../../services/api';
import { csvCell, download } from '../analysis/shared';
import { isOldBackend, OldBackendNote } from './SystemHealth';

export function AuditLog() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [errors, setErrors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true; setBusy(true);
    const t = window.setTimeout(() => {
      getAdminAudit(page, 20, q, errors).then(r => { if (!alive) return; setRows(r.rows); setPages(r.pages); setTotal(r.total); setError(null); })
        .catch(e => alive && setError(e.message)).finally(() => alive && setBusy(false));
    }, q ? 300 : 0);
    return () => { alive = false; window.clearTimeout(t); };
  }, [page, q, errors]);

  const exportCsv = () => download('nhat-ky-kiem-toan.csv', '﻿' + ['Thời điểm,Tài khoản,Email,Vai trò,Thao tác,Đối tượng,Mã kết quả',
    ...rows.map(r => [new Date(r.created_at).toLocaleString('vi-VN'), r.display_name, r.email, r.role, r.action, r.target, r.status].map(csvCell).join(','))].join('\r\n'), 'text/csv;charset=utf-8');

  if (isOldBackend(error)) return <OldBackendNote />;
  return (
    <section className="ap-card ap-audit">
      <header className="ap-audit-head">
        <h3><ShieldAlert size={16} />Nhật ký kiểm toán <small>{total.toLocaleString('vi-VN')} bản ghi</small></h3>
        <div className="ap-tools">
          <label className="ap-search"><Search size={14} /><input value={q} onChange={e => { setQ(e.target.value); setPage(1); }} placeholder="Tìm thao tác, đối tượng, tài khoản" aria-label="Tìm trong nhật ký" /></label>
          <label className="ap-check"><input type="checkbox" checked={errors} onChange={e => { setErrors(e.target.checked); setPage(1); }} />Chỉ thao tác lỗi</label>
          <button className="ap-btn" onClick={exportCsv} disabled={!rows.length}><Download size={14} />CSV trang này</button>
        </div>
      </header>
      {error && <p className="ap-note is-bad" role="alert">{error}</p>}
      <div className="ap-table"><table>
        <thead><tr><th>Thời điểm</th><th>Tài khoản</th><th>Thao tác</th><th>Đối tượng</th><th>Kết quả</th></tr></thead>
        <tbody>{rows.length === 0 ? <tr><td colSpan={5} className="ap-empty-row">{busy ? 'Đang tải…' : 'Không có bản ghi phù hợp.'}</td></tr> : rows.map((r, i) => (
          <tr key={i}>
            <td className="ap-nowrap"><b>{new Date(r.created_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</b><small>{new Date(r.created_at).toLocaleDateString('vi-VN')}</small></td>
            <td><b>{r.display_name || '—'}</b><small>{r.email || 'tài khoản đã xóa'}{r.role === 'ADMIN' ? ' · quản trị' : ''}</small></td>
            <td>{r.action}</td>
            <td className="ap-target" title={r.target}>{r.target || '—'}</td>
            <td><span className={`ap-status ${r.status >= 400 ? 'is-bad' : 'is-ok'}`}>{r.status >= 400 ? `Lỗi ${r.status}` : 'Thành công'}</span></td>
          </tr>))}</tbody>
      </table></div>
      <footer className="ap-pager">
        <button className="ap-btn" disabled={page <= 1 || busy} onClick={() => setPage(p => p - 1)} aria-label="Trang trước"><ChevronLeft size={15} /></button>
        <span>Trang <b>{page}</b> / {pages}</span>
        <button className="ap-btn" disabled={page >= pages || busy} onClick={() => setPage(p => p + 1)} aria-label="Trang sau"><ChevronRight size={15} /></button>
      </footer>
      <p className="ap-foot">Nhật ký chỉ ghi thao tác, đối tượng và kết quả; không lưu nội dung câu hỏi hay tài liệu.</p>
    </section>
  );
}
