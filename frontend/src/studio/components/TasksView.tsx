// Việc cần làm (đợt 6 + đợt 10): chỉ hiện khi đang mở một tổ chức. Đơn từ và duyệt theo cấp, thông báo của tổ chức.
// Kiểm tra theo quy định dùng kỹ năng sẵn có (Ai duyệt, Kiểm tra điều kiện); kết luận do luật, người có thẩm quyền quyết định.
import React, { useEffect, useState } from 'react';
import { BellRing, CheckCheck, ClipboardList, FilePlus2, Inbox, RefreshCw, Send, ShieldCheck, Undo2 } from 'lucide-react';
import {
  createRequest, decideRequest, getNotifications, listRequests, markNotificationsRead, OrgNotification, OrgRequest, runSkill, withdrawRequest,
} from '../services/api';
import { suggestLevel } from '../utils/approverLevel';
import { ToolHeader } from './analysis/shared';
import '../styles/pages-2b.css';

const KIND: Record<string, string> = { leave: 'Nghỉ phép', purchase: 'Mua sắm, tạm ứng', other: 'Khác' };
const STATUS: Record<string, { text: string; tone: string }> = {
  PENDING: { text: 'Chờ duyệt', tone: 'warn' }, APPROVED: { text: 'Đã duyệt', tone: 'ok' }, REJECTED: { text: 'Từ chối', tone: 'bad' }, WITHDRAWN: { text: 'Đã rút', tone: 'muted' },
};
const ACTION: Record<string, string> = { SUBMITTED: 'Gửi đơn', APPROVED: 'Duyệt', REJECTED: 'Từ chối', WITHDRAWN: 'Rút đơn' };

type Props = {
  spaceId: string; spaceName?: string; docIds: string[]; levelName: { MANAGER: string; EXECUTIVE: string };
  onOpenOrg: () => void; noteText: (n: OrgNotification) => string;
};

export const TasksView: React.FC<Props> = ({ spaceId, spaceName, docIds, levelName, onOpenOrg, noteText }) => {
  const [items, setItems] = useState<OrgNotification[] | null>(null);
  const [reqs, setReqs] = useState<{ mine: OrgRequest[]; to_me: OrgRequest[] } | null>(null);
  const [error, setError] = useState('');
  const [form, setForm] = useState({ kind: 'leave', title: '', details: '', days: '', level: '' as '' | 'MANAGER' | 'EXECUTIVE' });
  const [check, setCheck] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState('');
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = () => {
    setError('');
    getNotifications().then(r => setItems(r.items.filter(n => !n.space_id || n.space_id === spaceId))).catch(e => setError(e.message));
    listRequests(spaceId).then(setReqs).catch(e => setError(e.message));
  };
  useEffect(load, [spaceId]);
  const unread = (items ?? []).filter(n => !n.read);
  const readAll = async () => { await markNotificationsRead(unread.map(n => n.notification_id)); load(); };
  const askText = () => [form.title, form.details, form.days ? `${form.days} ngày` : ''].filter(Boolean).join('. ');

  const runCheck = async () => {
    setBusy('check'); setError('');
    try {
      const ask = askText();
      const [approver, conditions] = await Promise.all([
        runSkill('approver', ask, docIds).catch(() => null),
        form.kind === 'leave' ? runSkill('conditions', ask, docIds).catch(() => null) : Promise.resolve(null),
      ]);
      const a: any = approver?.data, c: any = conditions?.data;
      const result = {
        approver: a?.approver || '', rule: a?.rule || '', approver_citation: a?.citation || null, overall: c?.overall || null,
        conditions: (c?.conditions || []).map((x: any) => ({ condition: x.condition, verdict: x.verdict, citation: x.citation })),
      };
      setCheck(result);
      const lv = suggestLevel(result.approver);
      if (lv) setForm(f => (f.level ? f : { ...f, level: lv }));
      if (!a && !c) setError('Chưa kiểm tra được theo quy định (không có tài liệu phù hợp hoặc mô hình chưa sẵn sàng). Bạn vẫn gửi được đơn.');
    } finally { setBusy(''); }
  };
  const submit = async () => {
    if (!form.level) { setError('Chọn cấp duyệt trước khi gửi.'); return; }
    setBusy('send'); setError('');
    try {
      await createRequest(spaceId, { kind: form.kind, title: form.title, details: form.details, days: form.days ? Number(form.days) : null, approver_level: form.level, check_result: check ?? {} });
      setForm({ kind: 'leave', title: '', details: '', days: '', level: '' }); setCheck(null); load();
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };
  const decide = async (r: OrgRequest, d: 'APPROVED' | 'REJECTED') => {
    setBusy(r.request_id);
    try { await decideRequest(spaceId, r.request_id, d, notes[r.request_id] || ''); load(); } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };
  const withdraw = async (r: OrgRequest) => {
    if (!confirm(`Rút đơn “${r.title}”?`)) return;
    try { await withdrawRequest(spaceId, r.request_id); load(); } catch (e: any) { setError(e.message); }
  };

  const row = (r: OrgRequest, approve = false) => {
    const st = STATUS[r.status];
    return <li key={r.request_id} className="req-row">
      <div className="req-main">
        <span className={`req-st is-${st.tone}`}>{st.text}</span>
        <b>{r.title}</b>
        <small>{KIND[r.kind]}{r.days != null ? ` · ${r.days} ngày` : ''} · {levelName[r.approver_level]} duyệt{!r.mine ? ` · ${r.requester}` : ''}</small>
        {r.details && <p>{r.details}</p>}
        {(r.check_result?.approver || r.check_result?.overall) && <p className="req-check"><ShieldCheck size={13} />
          {r.check_result.approver && <>Theo quy định: {r.check_result.approver} duyệt. </>}
          {r.check_result.overall && <>Điều kiện: {r.check_result.overall === 'ELIGIBLE' ? 'đạt' : r.check_result.overall === 'NOT_ELIGIBLE' ? 'không đạt' : 'chưa đủ dữ kiện'}.</>}</p>}
        <ol className="req-hist">{r.history.map((h, i) => <li key={i}>{ACTION[h.action] ?? h.action} · {h.by} · {new Date(h.at).toLocaleString('vi-VN')}{h.note ? ` · “${h.note}”` : ''}</li>)}</ol>
      </div>
      <div className="req-acts">
        {approve && r.can_decide && <>
          <input aria-label={`Ghi chú cho đơn ${r.title}`} placeholder="Ghi chú (không bắt buộc)" value={notes[r.request_id] || ''}
            onChange={e => setNotes(n => ({ ...n, [r.request_id]: e.target.value }))} />
          <button className="btn btn-dark is-sm" disabled={busy === r.request_id} onClick={() => decide(r, 'APPROVED')}>Duyệt</button>
          <button className="btn btn-ghost is-sm" disabled={busy === r.request_id} onClick={() => decide(r, 'REJECTED')}>Từ chối</button></>}
        {r.mine && r.status === 'PENDING' && <button className="btn btn-ghost is-sm" onClick={() => withdraw(r)}><Undo2 size={14} />Rút đơn</button>}
      </div>
    </li>;
  };
  const pendingToMe = (reqs?.to_me ?? []).filter(r => r.can_decide);
  const handled = (reqs?.to_me ?? []).filter(r => !r.can_decide);

  return (
    <main className="pg tl tone-overview tsk">
      <div className="pg-col">
        <ToolHeader Icon={ClipboardList} title="Việc cần làm"
          desc={`Đơn từ, duyệt theo cấp và thông báo trong ${spaceName ?? 'tổ chức'}. Kết quả kiểm tra là gợi ý theo quy định; người có thẩm quyền quyết định cuối cùng.`}
          right={<button className="btn btn-ghost" onClick={load}><RefreshCw size={15} />Tải lại</button>} />
        {error && <p className="note is-error" role="alert">{error}</p>}
        <div className="tsk-cols">
          <section className="dz-card tsk-card">
            {reqs && pendingToMe.length === 0 && reqs.mine.length === 0 && handled.length === 0 ? <div className="tsk-empty">
              <h3><Inbox size={16} />Chưa có đơn nào</h3>
              <p>Đơn bạn gửi và đơn chờ bạn duyệt sẽ hiện ở đây. Một đơn đi qua:</p>
              <ul className="tsk-flow">
                <li><FilePlus2 size={16} /><b>Tạo đơn</b><small>Nghỉ phép, mua sắm, tạm ứng…</small></li>
                <li><ShieldCheck size={16} /><b>Kiểm tra theo quy định</b><small>AI tra nội quy: ai duyệt, có đủ điều kiện không</small></li>
                <li><Send size={16} /><b>Người duyệt nhận thông báo</b><small>{levelName.MANAGER} hoặc {levelName.EXECUTIVE} duyệt hay từ chối, có ghi chú</small></li>
              </ul>
            </div> : <>
            <header><h3><Inbox size={16} />Chờ tôi duyệt {pendingToMe.length > 0 && <span className="og-count is-alert">{pendingToMe.length}</span>}</h3></header>
            {reqs && pendingToMe.length === 0 && <p className="lib-empty">Không có đơn nào chờ bạn duyệt.</p>}
            <ul className="req-list">{pendingToMe.map(r => row(r, true))}</ul>
            <header><h3><Send size={16} />Đơn tôi đã gửi</h3></header>
            {reqs && reqs.mine.length === 0 && <p className="lib-empty">Bạn chưa gửi đơn nào.</p>}
            <ul className="req-list">{(reqs?.mine ?? []).map(r => row(r))}</ul>
            {handled.length > 0 && <><header><h3><CheckCheck size={16} />Đơn đã xử lý</h3></header>
              <ul className="req-list">{handled.slice(0, 10).map(r => row(r))}</ul></>}</>}
          </section>

          <section className="dz-card tsk-card req-form">
            <header><h3><FilePlus2 size={16} />Tạo đơn</h3></header>
            <label>Loại đơn<select value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}>
              {Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label>Tiêu đề<input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="Ví dụ: Xin nghỉ phép từ 2/12" /></label>
            <label>Nội dung<textarea rows={3} value={form.details} onChange={e => setForm({ ...form, details: e.target.value })} placeholder="Lý do, thời gian, số tiền…" /></label>
            {form.kind === 'leave' && <label>Số ngày<input type="number" min={0} step={0.5} value={form.days} onChange={e => setForm({ ...form, days: e.target.value })} /></label>}
            <button type="button" className="btn btn-ghost" disabled={!form.title.trim() || busy === 'check' || docIds.length === 0} onClick={runCheck}
              title={docIds.length === 0 ? 'Tổ chức chưa có tài liệu quy định để kiểm tra' : undefined}>
              {busy === 'check' ? <span className="spin is-dark" /> : <ShieldCheck size={15} />}Kiểm tra theo quy định</button>
            {docIds.length === 0 ? <small className="req-hint">Tổ chức chưa có tài liệu quy định (nội quy, quy chế) nên chưa kiểm tra được; vẫn gửi đơn được.</small>
              : !form.title.trim() && <small className="req-hint">Nhập tiêu đề để kiểm tra đơn theo quy định của tổ chức.</small>}
            {check && <div className="req-check-box">
              <p>{check.approver ? <>Theo quy định: <b>{check.approver}</b> duyệt.</> : 'Không thấy quy định cấp duyệt cho đơn này.'}</p>
              {check.rule && <small>{check.rule}</small>}
              {check.conditions?.some((c: any) => c.verdict !== 'UNKNOWN')
                ? <ul>{check.conditions.map((c: any, i: number) => <li key={i}>{c.verdict === 'MET' ? 'Đạt' : c.verdict === 'NOT_MET' ? 'Không đạt' : 'Chưa rõ'}: {c.condition}</li>)}</ul>
                : form.kind === 'leave' && <small>Chưa thấy điều kiện nghỉ phép rõ ràng trong tài liệu của tổ chức; người duyệt sẽ quyết định.</small>}
            </div>}
            <label>Cấp duyệt<select value={form.level} onChange={e => setForm({ ...form, level: e.target.value as '' | 'MANAGER' | 'EXECUTIVE' })}>
              <option value="">Chọn cấp duyệt…</option>
              <option value="MANAGER">{levelName.MANAGER} của phòng tôi</option>
              <option value="EXECUTIVE">{levelName.EXECUTIVE}</option></select></label>
            <button type="button" className="btn btn-dark" disabled={!form.title.trim() || !form.level || busy === 'send'} onClick={submit}><Send size={15} />Gửi đơn</button>
          </section>
        </div>

        <section className="dz-card tsk-card">
          <header><h3><BellRing size={16} />Thông báo {unread.length > 0 && <span className="og-count is-alert">{unread.length}</span>}</h3>
            {unread.length > 0 && <button className="btn btn-ghost is-sm" onClick={readAll}><CheckCheck size={14} />Đánh dấu đã đọc</button>}</header>
          {items && items.length === 0 && <p className="lib-empty">Không có thông báo.</p>}
          {items && items.length > 0 && <ul className="tsk-list">{items.slice(0, 30).map(n => <li key={n.notification_id} className={n.read ? '' : 'is-new'}>
            <b>{noteText(n)}</b><time>{new Date(n.created_at).toLocaleString('vi-VN')}</time></li>)}</ul>}
          <button className="btn btn-ghost is-sm tsk-org" onClick={onOpenOrg}>Duyệt thành viên mới ở trang Tổ chức</button>
        </section>
      </div>
    </main>
  );
};
