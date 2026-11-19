// Nhân sự · Tính phép năm và tiền làm thêm giờ: hệ số lấy từ nội quy (có trích dẫn, sửa được) -> nhập nhân viên
// -> máy chủ tính bằng công thức cố định; thiếu hệ số thì để trống kèm lý do, không giả định.
import React, { useState } from 'react';
import { AlertCircle, Calculator, Download, FileSpreadsheet, Plus, Sparkles, Trash2 } from 'lucide-react';
import { computePay, extractPayRates, parseTable, PayRow } from '../../services/api';
import { csvCell, Doc, DocPicker, download, ProcessRail, ToolHeader, useChunkViewer } from '../analysis/shared';
import { Meta, useDocs } from '../CaseworkViews';

const FIELDS: [string, string, string][] = [
  ['leave_base_days', 'Ngày phép năm (đủ 12 tháng)', 'ngày'], ['leave_extra_days', 'Cộng thêm theo thâm niên', 'ngày'],
  ['leave_every_years', 'Cứ đủ … năm thì cộng', 'năm'], ['ot_weekday_pct', 'Làm thêm ngày thường', '%'],
  ['ot_rest_pct', 'Làm thêm ngày nghỉ hằng tuần', '%'], ['ot_holiday_pct', 'Làm thêm ngày lễ', '%'], ['ot_month_cap', 'Giờ làm thêm tối đa/tháng', 'giờ'],
];
const COLS: [string, string][] = [['name', 'Họ tên'], ['months', 'Số tháng làm việc'], ['hourly', 'Lương giờ (đồng)'], ['weekday_hours', 'Giờ làm thêm ngày thường'],
  ['rest_hours', 'Giờ ngày nghỉ tuần'], ['holiday_hours', 'Giờ ngày lễ'], ['used_days', 'Ngày phép đã nghỉ']];
const HINT: Record<string, RegExp> = { name: /ten|ho ten|nhan vien/, months: /thang|tham nien/, hourly: /luong gio|luong/, weekday_hours: /thuong/,
  rest_hours: /nghi tuan|cuoi tuan|nghi hang tuan/, holiday_hours: /\ble\b|ngay le/, used_days: /da nghi|da dung/ };
type Emp = Record<string, string>;
const blank = (): Emp => Object.fromEntries(COLS.map(([k]) => [k, ''])) as Emp;
const money = (n: number | null) => (n == null ? '—' : n.toLocaleString('vi-VN') + ' đ');
// "1.200.000" là hàng nghìn; "1,5" và "1.5" đều là 1,5
const num = (s: string) => {
  const t = s.trim().replace(/\s/g, '');
  if (!t) return null;
  return /^\d{1,3}(\.\d{3})+(,\d+)?$/.test(t) ? Number(t.replace(/\./g, '').replace(',', '.')) : Number(t.replace(',', '.'));
};
const fold = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/gi, 'd').toLowerCase();

export const PayCalculator: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const { pickable, picked, setPicked, ids, nameOf } = useDocs(docs);
  const viewer = useChunkViewer();
  const [rates, setRates] = useState<Record<string, string>>({});
  const [cites, setCites] = useState<Record<string, string>>({});
  const [meta, setMeta] = useState<any>(null);
  const [emps, setEmps] = useState<Emp[]>([blank()]);
  const [rows, setRows] = useState<PayRow[] | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<string | null>(null);

  const getRates = async () => {
    setBusy('rates'); setError(null); setRows(null);
    try {
      const r = await extractPayRates(ids);
      setMeta(r);
      setRates(Object.fromEntries(FIELDS.map(([k]) => [k, r.rates[k] ? String(r.rates[k]!.value).replace('.', ',') : ''])));
      setCites(Object.fromEntries(FIELDS.filter(([k]) => r.rates[k]).map(([k]) => [k, r.rates[k]!.citation])));
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };
  const importTable = async (file?: File) => {
    if (!file) return;
    setBusy('table'); setError(null);
    try {
      const t = await parseTable(file);
      const idx = Object.fromEntries(COLS.map(([k]) => [k, t.columns.findIndex(c => HINT[k].test(fold(c)))]));
      setEmps(t.rows.slice(0, 500).map(r => Object.fromEntries(COLS.map(([k]) => [k, idx[k] >= 0 ? r[idx[k]] ?? '' : ''])) as Emp));
      setRows(null);
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };
  // giới hạn khớp máy chủ: tháng làm việc ≤ 720, giờ làm thêm ≤ 744/tháng, ngày phép đã nghỉ ≤ 366, không âm
  const LIMIT: Record<string, number> = { months: 720, hourly: 100_000_000, weekday_hours: 744, rest_hours: 744, holiday_hours: 744, used_days: 366 };
  const badCell = (k: string, v: string) => { if (v.trim() === '') return false; const n = num(v)!; return !Number.isFinite(n) || n < 0 || n > (LIMIT[k] ?? Infinity); };
  const badNumbers = emps.some(e => COLS.slice(1).some(([k]) => badCell(k, e[k]))) || FIELDS.some(([k]) => badCell(k, rates[k] ?? ''));
  const run = async () => {
    setBusy('run'); setError(null);
    try {
      const r = await computePay(Object.fromEntries(FIELDS.map(([k]) => [k, num(rates[k] ?? '')])),
        emps.map(e => ({ name: e.name, months: num(e.months), hourly: num(e.hourly), weekday_hours: num(e.weekday_hours) ?? 0,
          rest_hours: num(e.rest_hours) ?? 0, holiday_hours: num(e.holiday_hours) ?? 0, used_days: num(e.used_days) ?? 0 })));
      setRows(r.employees);
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };
  const exportCsv = () => rows && download('phep-nam-lam-them.csv', '﻿' + [['Nhân viên', 'Ngày phép năm', 'Phép còn lại', 'Giờ làm thêm', 'Tiền làm thêm (đ)', 'Ghi chú'].map(csvCell).join(','),
    ...rows.map(r => [r.name, r.leave_days ?? '', r.leave_left ?? '', r.overtime_hours, r.overtime_pay ?? '', r.notes.join(' ')].map(csvCell).join(','))].join('\r\n'), 'text/csv;charset=utf-8');

  return (
    <main className="pg tl tone-design">
      <div className="pg-col tv-col">
        <ToolHeader Icon={Calculator} title="Tính phép năm và tiền làm thêm giờ" desc="Lấy hệ số từ nội quy, nhập dữ liệu nhân viên, máy tính số ngày phép và tiền làm thêm theo công thức cố định." />
        <ProcessRail steps={[{ label: 'Hệ số từ nội quy', state: meta ? 'done' : 'current' }, { label: 'Dữ liệu nhân viên', state: rows ? 'done' : meta ? 'current' : 'todo' }, { label: 'Kết quả', state: rows ? 'done' : 'todo' }]} />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <h3 className="tk-step">1. Hệ số từ nội quy</h3>
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} legend="Nội quy, quy chế lương" />
          <div className="tv-actions"><button className="btn btn-dark" onClick={getRates} disabled={!!busy || !ids.length}>{busy === 'rates' ? <span className="spin" /> : <Sparkles size={15} />}Lấy hệ số từ nội quy</button></div>
          <div className="pc-grid">{FIELDS.map(([k, label, unit]) => <label key={k} className="tv-field"><span>{label}</span>
            <span className="pc-in"><input className="dz-input tk-num" inputMode="decimal" value={rates[k] ?? ''} onChange={e => { setRates(r => ({ ...r, [k]: e.target.value })); setCites(c => { const n = { ...c }; delete n[k]; return n; }); setRows(null); }} /><small>{unit}</small></span>
            {cites[k] ? <button type="button" className="tv-cite-count" onClick={() => viewer.show(cites[k])}>{nameOf(cites[k], meta?.evidence ?? [])}</button>
              : meta && <small className="is-muted">{(rates[k] ?? '') ? 'Nhập tay' : 'Không có trong nội quy'}</small>}</label>)}</div>
          {meta && <Meta r={{ ...meta, removed: 0 }} what="mục" />}
        </section>
        <section className="tv-setup">
          <h3 className="tk-step">2. Dữ liệu nhân viên</h3>
          <div className="tbl"><table>
            <thead><tr>{COLS.map(([, l]) => <th key={l}>{l}</th>)}<th /></tr></thead>
            <tbody>{emps.map((e, i) => <tr key={i}>{COLS.map(([k, l]) => <td key={k}>
              <input className={`dz-input${k === 'name' ? '' : ' tk-num'}`} aria-label={`${l} dòng ${i + 1}`} inputMode={k === 'name' ? 'text' : 'decimal'}
                value={e[k]} onChange={ev => { setEmps(es => es.map((x, j) => (j === i ? { ...x, [k]: ev.target.value } : x))); setRows(null); }} /></td>)}
              <td><button className="icon-btn is-sm" aria-label={`Xóa dòng ${i + 1}`} onClick={() => setEmps(es => (es.length > 1 ? es.filter((_, j) => j !== i) : [blank()]))}><Trash2 size={14} /></button></td></tr>)}</tbody>
          </table></div>
          <div className="tv-actions">
            <button className="btn btn-ghost" onClick={() => setEmps(es => [...es, blank()])}><Plus size={15} />Thêm nhân viên</button>
            <label className="btn btn-ghost tk-file"><FileSpreadsheet size={15} />{busy === 'table' ? 'Đang đọc…' : 'Nhập từ Excel/CSV'}<input type="file" accept=".xlsx,.csv" hidden onChange={e => { void importTable(e.target.files?.[0]); e.target.value = ''; }} /></label>
            <button className="btn btn-dark" onClick={run} disabled={!!busy || badNumbers}>{busy === 'run' ? <span className="spin" /> : <Calculator size={15} />}Tính</button>
            {badNumbers && <span className="muted-line">Có ô số không hợp lệ (số âm, chữ, hoặc vượt giới hạn: tối đa 720 tháng, 744 giờ, 366 ngày).</span>}
          </div>
        </section>
        {rows && <section className="dz-card">
          <div className="tbl"><table>
            <thead><tr><th>Nhân viên</th><th>Ngày phép năm</th><th>Phép còn lại</th><th>Giờ làm thêm</th><th>Tiền làm thêm</th><th>Ghi chú</th></tr></thead>
            <tbody>{rows.map((r, i) => <tr key={i}><td>{r.name}</td><td>{r.leave_days ?? '—'}</td>
              <td className={r.leave_left != null && r.leave_left < 0 ? 'is-bad' : ''}>{r.leave_left ?? '—'}</td><td>{r.overtime_hours.toLocaleString('vi-VN')}</td>
              <td>{money(r.overtime_pay)}</td><td>{r.notes.map((n, k) => <small key={k} className="tv-flag"><AlertCircle size={12} />{n}</small>)}</td></tr>)}</tbody>
          </table></div>
          <p className="is-muted">Phép năm dưới 12 tháng tính theo tỷ lệ số tháng (làm tròn xuống); tiền làm thêm = lương giờ × số giờ × tỷ lệ. Kiểm lại với bộ phận nhân sự trước khi chi trả.</p>
          <div className="tv-actions is-end"><button className="btn btn-ghost" onClick={exportCsv}><Download size={15} />Xuất CSV</button></div>
        </section>}
      </div>
      {viewer.modal}
    </main>
  );
};
