// Kết quả & công việc (Đợt 6): một trang nhiều tab: Đã lưu, Cần xem xét, Đơn từ, Thông báo. Mọi số và mục lấy từ máy chủ.
import React, { useEffect, useState } from 'react';
import { AlertTriangle, Archive, Bell, ClipboardList, FileWarning, GitCompareArrows, Inbox, ListChecks } from 'lucide-react';
import { ActivityRow, getActivity, getNotifications, libraryQuality, listRequests, OrgNotification, OrgRequest } from '../services/api';
import type { NavigationTab } from '../types';
import { serverDate } from '../utils/time';
import '../styles/results-hub.css';

export type HubTab = 'saved' | 'review' | 'requests' | 'notices';
type Review = { id: string; kind: 'approval' | 'quality' | 'watch'; title: string; detail: string; go: NavigationTab; action: string };
const fmt = new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' });

export const ResultsHub: React.FC<{
  tab: HubTab; onTab: (t: HubTab) => void; spaceId?: string; onGo: (t: NavigationTab) => void;
  noteText: (n: OrgNotification) => string; saved: React.ReactNode; requests?: React.ReactNode;
}> = ({ tab, onTab, spaceId, onGo, noteText, saved, requests }) => {
  const [review, setReview] = useState<Review[] | null>(null);
  const [notices, setNotices] = useState<{ org: OrgNotification[]; activity: ActivityRow[] } | null>(null);
  const [error, setError] = useState('');

  // "Cần xem xét": đơn chờ tôi duyệt, tài liệu có vấn đề chất lượng, thông báo tài liệu mới thay thế/mâu thuẫn chưa đọc
  useEffect(() => {
    let alive = true;
    setError('');
    Promise.all([
      spaceId ? listRequests(spaceId).catch(() => null) : Promise.resolve(null),
      libraryQuality().catch(() => null),
      getNotifications().catch(() => null),
    ]).then(([reqs, q, notes]) => {
      if (!alive) return;
      const out: Review[] = [];
      (reqs?.to_me ?? []).filter((r: OrgRequest) => r.status === 'PENDING' && r.can_decide).forEach(r =>
        out.push({ id: r.request_id, kind: 'approval', title: `Đơn chờ bạn duyệt: ${r.title}`, detail: `${r.requester}${r.days != null ? ` · ${r.days} ngày` : ''}`, go: 'results', action: 'Mở Đơn từ' }));
      (notes?.items ?? []).filter(n => n.kind === 'doc_watch' && !n.read).forEach(n =>
        out.push({ id: n.notification_id, kind: 'watch', title: `Tài liệu mới "${n.payload.source_name}"`, detail: noteText(n), go: n.payload.conflicts ? 'consistency' : 'compare', action: n.payload.conflicts ? 'Kiểm tra mâu thuẫn' : 'So sánh phiên bản' }));
      (q?.docs ?? []).forEach(d => d.issues.filter(i => i.level !== 'low').forEach((i, k) =>
        out.push({ id: `${d.source_id}-${k}`, kind: 'quality', title: d.source_name, detail: i.message, go: 'library', action: 'Mở Tài liệu' })));
      (q?.duplicates ?? []).forEach(dup => out.push({ id: `dup-${dup.a_id}-${dup.b_id}`, kind: 'quality', title: `Có thể trùng: ${dup.a} và ${dup.b}`, detail: `Giống nhau ${Math.round(dup.score * 100)}%`, go: 'library', action: 'Mở Tài liệu' }));
      setReview(out);
    }).catch(e => alive && setError(e.message));
    return () => { alive = false; };
  }, [spaceId]);
  useEffect(() => {
    if (tab !== 'notices' || notices) return;
    Promise.all([getNotifications().catch(() => ({ items: [] as OrgNotification[] })), getActivity(30).catch(() => [] as ActivityRow[])])
      .then(([o, a]) => setNotices({ org: o.items, activity: a })).catch(e => setError(e.message));
  }, [tab]);

  const TABS: { id: HubTab; label: string; Icon: typeof Archive; count?: number }[] = [
    { id: 'saved', label: 'Đã lưu', Icon: Archive },
    { id: 'review', label: 'Cần xem xét', Icon: ListChecks, count: review?.length },
    { id: 'requests', label: 'Đơn từ', Icon: ClipboardList },
    { id: 'notices', label: 'Thông báo', Icon: Bell },
  ];
  const ICON = { approval: ClipboardList, quality: FileWarning, watch: GitCompareArrows };

  return (
    <div className="rh">
      <nav className="rh-tabs" role="tablist" aria-label="Kết quả và công việc">
        {TABS.map(t => <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'is-on' : ''} onClick={() => onTab(t.id)}>
          <t.Icon size={16} />{t.label}{t.count ? <em>{t.count}</em> : null}</button>)}
      </nav>
      {error && <p className="note is-error rh-pad" role="alert">{error}</p>}
      {tab === 'saved' && saved}
      {tab === 'requests' && (requests ?? <section className="rh-empty"><Inbox size={28} /><h3>Đơn từ dùng trong không gian tổ chức</h3>
        <p>Chọn một tổ chức ở ô không gian trên thanh trên cùng, hoặc tạo/tham gia tổ chức để gửi và duyệt đơn theo cấp.</p>
        <button className="btn btn-dark" onClick={() => onGo('organization')}>Mở trang Tổ chức</button></section>)}
      {tab === 'review' && <section className="rh-list" aria-label="Cần xem xét">
        {review === null ? <p className="muted-line"><span className="spin is-dark" />Đang tải…</p>
          : review.length === 0 ? <div className="rh-empty"><ListChecks size={28} /><h3>Không có gì cần xem xét</h3><p>Đơn chờ duyệt, tài liệu trùng hoặc lỗi, tài liệu mới thay thế bản cũ sẽ hiện ở đây.</p></div>
          : review.map(r => { const I = ICON[r.kind]; return <article key={r.id} className={`rh-item is-${r.kind}`}>
            <span className="rh-ico"><I size={17} /></span><div><b>{r.title}</b><small>{r.detail}</small></div>
            <button className="btn btn-ghost is-sm" onClick={() => r.kind === 'approval' ? onTab('requests') : onGo(r.go)}>{r.action}</button></article>; })}
      </section>}
      {tab === 'notices' && <section className="rh-list" aria-label="Thông báo">
        {!notices ? <p className="muted-line"><span className="spin is-dark" />Đang tải…</p> : <>
          <h3 className="rh-h">Tổ chức</h3>
          {notices.org.length === 0 ? <p className="rh-note">Chưa có thông báo tổ chức.</p> : notices.org.map(n => <article key={n.notification_id} className={`rh-item${n.read ? '' : ' is-unread'}`}>
            <span className="rh-ico"><Bell size={16} /></span><div><b>{noteText(n)}</b><small>{fmt.format(serverDate(n.created_at))}</small></div></article>)}
          <h3 className="rh-h">Hoạt động của bạn</h3>
          {notices.activity.length === 0 ? <p className="rh-note">Chưa có hoạt động.</p> : notices.activity.map((a, i) => <article key={i} className={`rh-item${a.status >= 400 ? ' is-bad' : ''}`}>
            <span className="rh-ico">{a.status >= 400 ? <AlertTriangle size={16} /> : <Archive size={16} />}</span><div><b>{a.action}</b><small>{fmt.format(serverDate(a.created_at))}</small></div></article>)}
        </>}
      </section>}
    </div>
  );
};
