// Pháp lý · Hiệu lực văn bản: đọc số hiệu, ngày ban hành, ngày có hiệu lực, văn bản bị thay thế trong kho bằng luật
// nhận dạng cố định (không dùng mô hình), nên kết quả tức thì và lặp lại được.
import React, { useState } from 'react';
import { AlertCircle, Download, Scale } from 'lucide-react';
import { documentValidity, DocValidity } from '../../services/api';
import { csvCell, Doc, DocPicker, download, ToolHeader } from '../analysis/shared';
import { useDocs } from '../CaseworkViews';

const STATUS: Record<DocValidity['status'], [string, string]> = {
  IN_FORCE: ['Đang có hiệu lực', 'complete'], NOT_YET: ['Chưa có hiệu lực', 'partial'], REPLACED: ['Đã bị thay thế', 'failed'], UNKNOWN: ['Chưa xác định', 'muted'],
};
const vnDate = (iso: string | null) => (iso ? iso.split('-').reverse().join('/') : '—');

export const DocumentValidity: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const { pickable, picked, setPicked, ids } = useDocs(docs);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Awaited<ReturnType<typeof documentValidity>> | null>(null);

  const run = async () => {
    setBusy(true); setError(null);
    try { setResult(await documentValidity(ids)); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const exportCsv = () => result && download('hieu-luc-van-ban.csv', '﻿' + [['Tài liệu', 'Số hiệu', 'Loại', 'Ngày ban hành', 'Ngày hiệu lực', 'Tình trạng', 'Ghi chú', 'Thay thế/bãi bỏ', 'Dẫn chiếu'].map(csvCell).join(','),
    ...result.documents.map(d => [d.source_name, d.number ?? '', d.kind, vnDate(d.issued), vnDate(d.effective), STATUS[d.status][0], d.status_note, d.replaces.join('; '), d.references.join('; ')].map(csvCell).join(','))].join('\r\n'), 'text/csv;charset=utf-8');
  const count = (s: DocValidity['status']) => result?.documents.filter(d => d.status === s).length ?? 0;

  return (
    <main className="pg tl tone-trace">
      <div className="pg-col tv-col">
        <ToolHeader Icon={Scale} title="Hiệu lực văn bản" desc="Liệt kê số hiệu, ngày ban hành, ngày có hiệu lực của các văn bản trong kho và chỉ ra văn bản đã bị văn bản khác thay thế, bãi bỏ." />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} disabled={busy} legend="Văn bản cần kiểm" />
          <div className="tv-actions"><button className="btn btn-dark" onClick={run} disabled={busy || !ids.length}>{busy ? <span className="spin" /> : <Scale size={15} />}Kiểm tra hiệu lực</button></div>
        </section>
        {result && <section className="dz-card">
          <p className="chips">{(Object.keys(STATUS) as DocValidity['status'][]).map(s => <span key={s} className={`cht-status is-${STATUS[s][1]}`}>{STATUS[s][0]}: {count(s)}</span>)}</p>
          <div className="tbl"><table>
            <thead><tr><th>Tài liệu</th><th>Số hiệu</th><th>Ngày ban hành</th><th>Hiệu lực từ</th><th>Tình trạng</th><th>Thay thế, bãi bỏ</th><th>Dẫn chiếu</th></tr></thead>
            <tbody>{result.documents.map(d => <tr key={d.source_id}>
              <td>{d.source_name}{d.kind && <small className="cw-reason">{d.kind}</small>}</td><td>{d.number ?? <span className="is-muted">Không thấy</span>}</td>
              <td>{vnDate(d.issued)}</td><td>{vnDate(d.effective)}</td>
              <td><span className={`cht-status is-${STATUS[d.status][1]}`}>{STATUS[d.status][0]}</span><small className="cw-reason">{d.status_note}</small></td>
              <td>{d.replaces.join(', ') || '—'}</td><td>{d.references.slice(0, 6).join(', ') || '—'}{d.references.length > 6 && ` +${d.references.length - 6}`}</td></tr>)}</tbody>
          </table></div>
          <p className="is-muted">Đọc theo mẫu trình bày văn bản (“Số: …”, “có hiệu lực từ ngày …”, “thay thế …”) và đối chiếu với ngày hôm nay ({vnDate(result.today)}); chỉ biết văn bản bị thay thế khi văn bản thay thế cũng nằm trong kho.</p>
          <div className="tv-actions is-end"><button className="btn btn-ghost" onClick={exportCsv}><Download size={15} />Xuất CSV</button></div>
        </section>}
      </div>
    </main>
  );
};
