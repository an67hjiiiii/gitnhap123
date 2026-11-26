// Kết quả & công việc: một trang 3 tab gọn: Đã lưu, Cần xem xét, Đơn từ.
// Thông báo được quản lý tập trung tại một đầu mối duy nhất (nút Chuông góc trên → trang Thông báo).
import React, { useEffect, useState } from 'react';
import { Archive, Bell, ClipboardList, FileWarning, GitCompareArrows, Inbox, ListChecks } from 'lucide-react';
import { getNotifications, libraryQuality, listRequests, OrgNotification, OrgRequest } from '../services/api';
import type { NavigationTab } from '../types';
import '../styles/results-hub.css';

export type HubTab = 'saved' | 'review' | 'requests';
type Review = { id: string; kind: 'approval' | 'quality' | 'watch'; title: string; detail: string; go: NavigationTab; action: string };

export const ResultsHub: React.FC<{
  tab: HubTab; onTab: (t: HubTab) => void; spaceId?: string; onGo: (t: NavigationTab) => void;
  noteText: (n: OrgNotification) => string; saved: React.ReactNode; requests?: React.ReactNode;
}> = ({ tab, onTab, spaceId, onGo, noteText, saved, requests }) => {
  const [review, setReview] = useState<Review[] | null>(null);
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

  const TABS: { id: HubTab; label: string; Icon: typeof Archive; count?: number }[] = [
    { id: 'saved', label: 'Đã lưu', Icon: Archive },
    { id: 'review', label: 'Cần xem xét', Icon: ListChecks, count: review?.length },
    { id: 'requests', label: 'Đơn từ', Icon: ClipboardList },
  ];
  const ICON = { approval: ClipboardList, quality: FileWarning, watch: GitCompareArrows };

  return (
    <div className="rh">
      <nav className="rh-tabs" role="tablist" aria-label="Kết quả và công việc">
        {TABS.map(t => <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'is-on' : ''} onClick={() => onTab(t.id)}>
          <t.Icon size={16} />{t.label}{t.count ? <em>{t.count}</em> : null}</button>)}
        <button type="button" className="rh-notif-link" onClick={() => onGo('notifications')} title="Mở trung tâm Thông báo tập trung">
          <Bell size={15} />Thông báo
        </button>
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
    </div>
  );
};
