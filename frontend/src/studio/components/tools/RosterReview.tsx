// Giáo dục · Xét duyệt theo danh sách: ngưỡng lấy từ quy chế (có trích dẫn, người dùng sửa được) -> gán cột của bảng điểm
// -> máy chủ so sánh từng hàng bằng mã cố định (không dùng mô hình) -> danh sách Đạt / Không đạt / Thiếu số liệu.
import React, { useMemo, useState } from 'react';
import { AlertCircle, Download, FileSpreadsheet, Plus, Sparkles, Trash2, Users } from 'lucide-react';
import { evaluateRoster, extractThresholds, Op, parseTable, RosterResult, Table, Threshold } from '../../services/api';
import { csvCell, Doc, DocPicker, download, ProcessRail, ToolHeader, useChunkViewer } from '../analysis/shared';
import { Meta, useDocs } from '../CaseworkViews';

const PRESETS = ['Xét học bổng khuyến khích học tập', 'Xét công nhận tốt nghiệp', 'Xét cảnh báo học tập'];
const OPS: Op[] = ['>=', '>', '<=', '<', '='];
const OP_TEXT: Record<Op, string> = { '>=': 'từ … trở lên', '>': 'lớn hơn', '<=': 'không quá', '<': 'dưới', '=': 'bằng' };
type Rule = Threshold & { column: number | null; text: string };
const STATUS = { PASS: ['Đạt', 'complete'], FAIL: ['Không đạt', 'failed'], MISSING: ['Thiếu số liệu', 'partial'] } as const;

// Gợi ý cột theo tên: "Điểm rèn luyện" -> cột có chữ "rèn luyện"
const fold = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/gi, 'd').toLowerCase();
const guessColumn = (label: string, columns: string[]) => {
  const words = fold(label).split(/\W+/).filter(w => w.length > 1 && !['diem', 'tu', 'tro', 'len', 'hoc'].includes(w));
  let best = -1, score = 0;
  columns.forEach((c, i) => { const s = words.filter(w => fold(c).includes(w)).length; if (s > score) { best = i; score = s; } });
  return best >= 0 ? best : null;
};

export const RosterReview: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const { pickable, picked, setPicked, ids, nameOf } = useDocs(docs);
  const viewer = useChunkViewer();
  const [topic, setTopic] = useState(PRESETS[0]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [meta, setMeta] = useState<any>(null);
  const [table, setTable] = useState<Table | null>(null);
  const [fileName, setFileName] = useState('');
  const [idCol, setIdCol] = useState<number | null>(0);
  const [result, setResult] = useState<RosterResult | null>(null);
  const [filter, setFilter] = useState<'ALL' | 'PASS' | 'FAIL' | 'MISSING'>('ALL');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<string | null>(null);

  // chỉ dùng ngưỡng đã gán cột và có giá trị số (mô hình đôi khi lấy cả mức thưởng: để trống cột là bỏ qua)
  const active = rules.filter(r => r.column !== null && Number.isFinite(r.value) && r.label.trim());
  const ready = active.length > 0 && !!table;
  const [used, setUsed] = useState<Rule[]>([]);
  const setRule = (i: number, patch: Partial<Rule>) => { setRules(rs => rs.map((r, k) => (k === i ? { ...r, ...patch } : r))); setResult(null); };

  const getRules = async () => {
    setBusy('rules'); setError(null); setResult(null);
    try {
      const r = await extractThresholds(topic.trim(), ids);
      setMeta(r);
      setRules(r.rules.map(x => ({ ...x, text: String(x.value).replace('.', ','), column: table ? guessColumn(x.label, table.columns) : null })));
      if (!r.rules.length) setError('Không tìm thấy ngưỡng có con số trong tài liệu đã chọn. Có thể thêm ngưỡng bằng tay.');
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };
  const loadTable = async (file?: File) => {
    if (!file) return;
    setBusy('table'); setError(null); setResult(null);
    try {
      const t = await parseTable(file);
      setTable(t); setFileName(file.name); setIdCol(0);
      // bảng mới có thể ít cột hơn: cột cũ không còn thì gợi ý lại theo tên
      setRules(rs => rs.map(r => ({ ...r, column: r.column !== null && r.column < t.columns.length ? r.column : guessColumn(r.label, t.columns) })));
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };
  const run = async () => {
    if (!table) return;
    setBusy('run'); setError(null);
    try { setUsed(active); setResult(await evaluateRoster(active.map(r => ({ label: r.label, op: r.op, value: r.value, column: r.column! })), table.columns, table.rows, idCol)); }
    catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };
  const exportCsv = () => {
    if (!result) return;
    const head = ['Đối tượng', 'Kết quả', ...used.map(r => `${r.label} (${r.op} ${r.value})`)];
    const body = result.results.map(x => [x.name, STATUS[x.status][0], ...x.checks.map(c => `${c.value || '—'} (${c.state === 'pass' ? 'đạt' : c.state === 'fail' ? 'không đạt' : 'thiếu'})`)].map(csvCell).join(','));
    download(`xet-duyet-${fileName.replace(/\.[^.]+$/, '') || 'danh-sach'}.csv`, '﻿' + [head.map(csvCell).join(','), ...body].join('\r\n'), 'text/csv;charset=utf-8');
  };
  const shown = useMemo(() => result?.results.filter(r => filter === 'ALL' || r.status === filter) ?? [], [result, filter]);

  return (
    <main className="pg tl tone-trace">
      <div className="pg-col tv-col">
        <ToolHeader Icon={Users} title="Xét duyệt theo danh sách" desc="Lấy ngưỡng từ quy chế, tải bảng điểm, máy so sánh từng sinh viên và ra danh sách đạt, không đạt, thiếu số liệu. Phép so sánh không dùng mô hình." />
        <ProcessRail steps={[
          { label: 'Ngưỡng từ quy chế', state: rules.length ? 'done' : 'current' },
          { label: 'Bảng danh sách', state: table ? 'done' : rules.length ? 'current' : 'todo' },
          { label: 'Kết quả', state: result ? 'done' : ready ? 'current' : 'todo' },
        ]} />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}

        <section className="tv-setup">
          <h3 className="tk-step">1. Ngưỡng xét duyệt</h3>
          <div className="chips">{PRESETS.map(p => <button key={p} type="button" className={`chip${topic === p ? ' is-on' : ''}`} onClick={() => setTopic(p)}>{p}</button>)}</div>
          <label className="tv-field"><span>Loại xét duyệt</span><input className="dz-input" value={topic} onChange={e => setTopic(e.target.value)} maxLength={300} /></label>
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} legend="Quy chế, quy định" />
          <div className="tv-actions">
            <button className="btn btn-dark" onClick={getRules} disabled={!!busy || ids.length === 0 || topic.trim().length < 3}>{busy === 'rules' ? <span className="spin" /> : <Sparkles size={15} />}Lấy ngưỡng từ quy chế</button>
            <button className="btn btn-ghost" onClick={() => setRules(rs => [...rs, { label: '', op: '>=', value: NaN, text: '', unit: '', citation: '', column: null }])}><Plus size={15} />Thêm ngưỡng</button>
          </div>
          {rules.length > 0 && <div className="tbl"><table>
            <thead><tr><th>Tiêu chí</th><th>So sánh</th><th>Ngưỡng</th><th>Cột trong bảng</th><th>Căn cứ</th><th /></tr></thead>
            <tbody>{rules.map((r, i) => <tr key={i}>
              <td><input className="dz-input" aria-label="Tiêu chí" value={r.label} onChange={e => setRule(i, { label: e.target.value })} /></td>
              <td><select aria-label="Phép so sánh" value={r.op} onChange={e => setRule(i, { op: e.target.value as Op })}>{OPS.map(o => <option key={o} value={o}>{o} ({OP_TEXT[o]})</option>)}</select></td>
              <td><input className="dz-input tk-num" aria-label="Ngưỡng" inputMode="decimal" value={r.text}
                onChange={e => { const t = e.target.value; setRule(i, { text: t, value: t.trim() ? Number(t.replace(',', '.')) : NaN }); }} /> <small>{r.unit}</small></td>
              <td><select aria-label="Cột trong bảng" value={r.column ?? ''} onChange={e => setRule(i, { column: e.target.value === '' ? null : Number(e.target.value) })} disabled={!table}>
                <option value="">{table ? 'Chọn cột…' : 'Tải bảng trước'}</option>{table?.columns.map((c, k) => <option key={k} value={k}>{c}</option>)}</select></td>
              <td>{r.citation ? <button className="tv-cite-count" onClick={() => viewer.show(r.citation)}>{nameOf(r.citation, meta?.evidence ?? [])}</button> : <small className="is-muted">Nhập tay</small>}</td>
              <td><button className="icon-btn is-sm" aria-label="Xóa ngưỡng" onClick={() => { setRules(rs => rs.filter((_, k) => k !== i)); setResult(null); }}><Trash2 size={14} /></button></td>
            </tr>)}</tbody>
          </table></div>}
          {meta && <Meta r={{ ...meta, removed: meta.removed ?? 0 }} what="ngưỡng" />}
        </section>

        <section className="tv-setup">
          <h3 className="tk-step">2. Bảng danh sách (Excel .xlsx hoặc .csv, hàng đầu là tên cột)</h3>
          <label className="btn btn-ghost tk-file"><FileSpreadsheet size={15} />{busy === 'table' ? 'Đang đọc…' : fileName || 'Chọn tệp bảng điểm'}
            <input type="file" accept=".xlsx,.csv" hidden onChange={e => { void loadTable(e.target.files?.[0]); e.target.value = ''; }} /></label>
          {table && <>
            <p className="muted-line">{table.rows.length} hàng · {table.columns.length} cột{table.truncated && ' · chỉ đọc 2.000 hàng đầu'}</p>
            <label className="tv-field tk-inline"><span>Cột tên/mã đối tượng</span>
              <select value={idCol ?? ''} onChange={e => setIdCol(e.target.value === '' ? null : Number(e.target.value))}>
                <option value="">Theo số hàng</option>{table.columns.map((c, k) => <option key={k} value={k}>{c}</option>)}</select></label>
          </>}
          <div className="tv-actions"><button className="btn btn-dark" onClick={run} disabled={!ready || !!busy}>{busy === 'run' ? <span className="spin" /> : <Users size={15} />}Xét duyệt {table ? `${table.rows.length} hàng` : ''}</button>
            {table && rules.length > active.length && <span className="muted-line">{rules.length - active.length} ngưỡng chưa gán cột hoặc thiếu giá trị sẽ không được dùng.</span>}</div>
        </section>

        {result && <section className="dz-card">
          <div className="seg tv-seg">{(['ALL', 'PASS', 'FAIL', 'MISSING'] as const).map(k => (
            <button key={k} className={filter === k ? 'is-on' : ''} aria-pressed={filter === k} onClick={() => setFilter(k)}>
              {k === 'ALL' ? `Tất cả ${result.summary.total}` : `${STATUS[k][0]} ${result.summary[k]}`}</button>))}</div>
          <div className="tbl"><table>
            <thead><tr><th>Đối tượng</th><th>Kết quả</th>{used.map((r, i) => <th key={i}>{r.label} {r.op} {String(r.value).replace('.', ',')}</th>)}</tr></thead>
            <tbody>{shown.map(x => <tr key={x.row}><td>{x.name}</td>
              <td><span className={`cht-status is-${STATUS[x.status][1]}`}>{STATUS[x.status][0]}</span></td>
              {x.checks.map((c, i) => <td key={i} className={c.state === 'pass' ? 'is-ok' : c.state === 'fail' ? 'is-bad' : ''}>{c.value || <span className="is-muted">trống</span>}</td>)}</tr>)}</tbody>
          </table></div>
          <p className="is-muted">So sánh bằng mã cố định trên số liệu của bảng; ngưỡng lấy từ tài liệu đã chọn và có thể đã được bạn sửa.</p>
          <div className="tv-actions is-end"><button className="btn btn-ghost" onClick={exportCsv}><Download size={15} />Xuất danh sách (CSV)</button></div>
        </section>}
      </div>
      {viewer.modal}
    </main>
  );
};
