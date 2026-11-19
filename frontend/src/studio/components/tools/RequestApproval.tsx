// Nhân sự · Duyệt đơn từ: điền đơn theo mẫu -> kiểm điều kiện theo nội quy (luật cố định suy ra kết luận) và tìm cấp duyệt
// (tên người/đơn vị duyệt phải có nguyên văn trong nội quy).
import React, { useState } from 'react';
import { AlertCircle, CheckCircle2, CircleHelp, FileSignature, UserCheck, XCircle } from 'lucide-react';
import { checkConditions, ConditionResult, findApprover } from '../../services/api';
import { Doc, DocPicker, ToolHeader, useChunkViewer } from '../analysis/shared';
import { Meta, useDocs } from '../CaseworkViews';

type Kind = 'leave' | 'advance' | 'purchase' | 'overtime' | 'other';
const KINDS: Record<Kind, { label: string; fields: [string, string, string][] }> = {
  leave: { label: 'Nghỉ phép', fields: [['days', 'Số ngày xin nghỉ', '6'], ['notice', 'Gửi đơn trước (ngày làm việc)', '2'], ['left', 'Số ngày phép còn lại', '8'], ['years', 'Thâm niên (năm)', '3']] },
  advance: { label: 'Tạm ứng', fields: [['amount', 'Số tiền tạm ứng (đồng)', '15.000.000'], ['purpose', 'Mục đích', 'Công tác phí']] },
  purchase: { label: 'Mua sắm', fields: [['amount', 'Giá trị (đồng)', '50.000.000'], ['item', 'Hạng mục', 'Máy tính xách tay']] },
  overtime: { label: 'Làm thêm giờ', fields: [['hours', 'Số giờ', '10'], ['day', 'Loại ngày (thường/nghỉ tuần/lễ)', 'ngày thường'], ['month_total', 'Tổng giờ làm thêm trong tháng', '35']] },
  other: { label: 'Khác', fields: [['detail', 'Nội dung đơn', '']] },
};
const VERDICT = { MET: ['Đạt', 'complete'], NOT_MET: ['Không đạt', 'failed'], UNKNOWN: ['Chưa xác định', 'partial'] } as const;
const OVERALL: Record<string, [string, string, typeof CheckCircle2]> = {
  ELIGIBLE: ['Đơn đáp ứng điều kiện', 'ok', CheckCircle2], NOT_ELIGIBLE: ['Đơn chưa đáp ứng điều kiện', 'bad', XCircle],
  INSUFFICIENT_INFO: ['Thiếu thông tin để kết luận', 'warn', CircleHelp], NO_RULE: ['Không tìm thấy quy định', 'muted', CircleHelp], UNRESOLVED: ['Chưa trích được điều kiện', 'warn', CircleHelp],
};

export const RequestApproval: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const { pickable, picked, setPicked, ids, nameOf } = useDocs(docs);
  const viewer = useChunkViewer();
  const [kind, setKind] = useState<Kind>('leave');
  const [form, setForm] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState<ConditionResult | null>(null);
  const [approver, setApprover] = useState<Awaited<ReturnType<typeof findApprover>> | null>(null);

  const fields = KINDS[kind].fields;
  const filled = fields.filter(([k]) => (form[k] ?? '').trim());
  const caseText = filled.map(([k, label]) => `${label}: ${form[k].trim()}`).join('; ');
  const request = `Đơn ${KINDS[kind].label.toLowerCase()}. ${caseText}`;
  const run = async () => {
    setBusy(true); setError(null); setCheck(null); setApprover(null);
    try {
      const [c, a] = await Promise.all([checkConditions(`Đơn ${KINDS[kind].label.toLowerCase()} này có đáp ứng điều kiện theo quy định không?`, caseText, ids), findApprover(request, ids)]);
      setCheck(c); setApprover(a);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const o = check ? OVERALL[check.overall] : null;

  return (
    <main className="pg tl tone-security">
      <div className="pg-col tv-col">
        <ToolHeader Icon={FileSignature} title="Duyệt đơn từ" desc="Điền đơn nghỉ phép, tạm ứng, mua sắm, làm thêm giờ; hệ thống kiểm từng điều kiện theo nội quy và chỉ ra cấp có thẩm quyền duyệt." />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <div className="seg tv-seg" role="radiogroup" aria-label="Loại đơn">{(Object.keys(KINDS) as Kind[]).map(k => (
            <button key={k} role="radio" aria-checked={kind === k} className={kind === k ? 'is-on' : ''} onClick={() => { setKind(k); setForm({}); setCheck(null); setApprover(null); }}>{KINDS[k].label}</button>))}</div>
          <div className="pc-grid">{fields.map(([k, label, ph]) => <label key={k} className="tv-field"><span>{label}</span>
            <input className="dz-input" value={form[k] ?? ''} placeholder={ph ? `Ví dụ: ${ph}` : ''} maxLength={300} onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))} /></label>)}</div>
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} disabled={busy} legend="Nội quy, quy chế" />
          <div className="tv-actions"><button className="btn btn-dark" onClick={run} disabled={busy || !filled.length || !ids.length || caseText.length < 3}>{busy ? <span className="spin" /> : <FileSignature size={15} />}{busy ? 'Đang kiểm…' : 'Kiểm đơn'}</button></div>
        </section>
        {check && o && <>
          <section className={`cw-verdict is-${o[1]}`} role="status">{React.createElement(o[2], { size: 22 })}<div><b>{o[0]}</b><p>{check.note || 'Kết luận do luật cố định suy ra từ từng điều kiện có trích dẫn.'}</p></div></section>
          <section className="dz-card ra-approver"><UserCheck size={18} />{approver?.approver
            ? <div><b>Cấp duyệt: {approver.approver}</b><p>{approver.rule}</p>{approver.citation && <button className="tv-cite-count" onClick={() => viewer.show(approver.citation!)}>{nameOf(approver.citation, check.evidence)}</button>}</div>
            : <div><b>Chưa xác định cấp duyệt</b><p>Nội quy đã chọn không nêu rõ ai duyệt loại đơn này.</p></div>}</section>
          {check.conditions.length > 0 && <div className="tbl"><table>
            <thead><tr><th>Điều kiện trong nội quy</th><th>Thông tin trong đơn</th><th>Kết luận</th><th>Căn cứ</th></tr></thead>
            <tbody>{check.conditions.map((c, i) => <tr key={i}><td>{c.condition}{c.reason && <small className="cw-reason">{c.reason}</small>}</td>
              <td>{c.case_fact || <span className="is-muted">Đơn không nêu</span>}</td>
              <td><span className={`cht-status is-${VERDICT[c.verdict][1]}`}>{VERDICT[c.verdict][0]}</span></td>
              <td><button className="tv-cite-count" onClick={() => viewer.show(c.citation)}>{nameOf(c.citation, check.evidence)}</button></td></tr>)}</tbody>
          </table></div>}
          <Meta r={check} what="điều kiện" />
        </>}
      </div>
      {viewer.modal}
    </main>
  );
};
