// Trang Thông báo (21/11): gộp thông báo tổ chức và hoạt động thật của tài khoản, lọc theo loại, nhóm theo ngày.
// Mở trang thì đánh dấu đã đọc ở máy chủ, nhưng chấm "chưa đọc" vẫn giữ trong lần xem này để người dùng thấy cái mới.
import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Bell, BellOff, Building2, CheckCheck, ClipboardCheck, FileText, FileWarning, Inbox, MailPlus, RefreshCw } from 'lucide-react';
import { NavigationTab, Workspace } from '../types';
import { ActivityRow, answerInvite, getActivity, getNotifications, markNotificationsRead, myInvites, OrgNotification, orgTerms } from '../services/api';
import { noteIcon, orgNoteText } from './Header';
import { ToolHeader } from './analysis/shared';
import { serverDate } from '../utils/time';

const SEEN_KEY = 'orchestriq-notif-seen';
// mã nội bộ (usr_…, src_…) không có nghĩa với người đọc
const RAW_ID = /^(usr|sp|src|inv|shr|dep|rs|rpt|ws)_[A-Za-z0-9_-]+$/;

type Item = { id: string; kind: 'org' | 'activity'; title: string; sub?: string; go?: NavigationTab; Icon: React.ComponentType<{ size?: number }>; at: Date; unread: boolean; bad?: boolean; invite?: string };
type Filter = 'all' | 'unread' | 'org' | 'activity';

// loại thông báo tổ chức → nhãn, biểu tượng, trang mở khi bấm "Mở"
function orgKind(n: OrgNotification): { sub: string; Icon: Item['Icon']; go?: NavigationTab } {
  if (n.kind === 'invite') return { sub: 'Lời mời', Icon: MailPlus };
  if (n.kind === 'doc_watch') return n.payload?.conflicts ? { sub: 'Tài liệu', Icon: FileWarning, go: 'consistency' } : { sub: 'Tài liệu', Icon: FileText, go: 'library' };
  if (/^source_|^drafts_/.test(n.kind)) return { sub: 'Tài liệu', Icon: FileText, go: 'library' };
  if (/^request_/.test(n.kind)) return { sub: 'Đơn từ', Icon: ClipboardCheck, go: 'tasks' };
  return { sub: 'Tổ chức', Icon: Building2, go: 'organization' };
}

function ago(d: Date) {
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 60) return 'vừa xong';
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }) + ' · ' + d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
}
function dayGroup(d: Date) {
  const start = new Date(); start.setHours(0, 0, 0, 0);
  const diff = (start.getTime() - new Date(d).setHours(0, 0, 0, 0)) / 86400000;
  return diff <= 0 ? 'Hôm nay' : diff === 1 ? 'Hôm qua' : diff < 7 ? '7 ngày qua' : 'Cũ hơn';
}

export const NotificationsView: React.FC<{ workspaces: Workspace[]; onGo: (tab: NavigationTab) => void; onOrgChanged?: () => void }> = ({ workspaces, onGo, onOrgChanged }) => {
  const [org, setOrg] = useState<OrgNotification[]>([]);
  const [acts, setActs] = useState<ActivityRow[]>([]);
  const [openInvites, setOpenInvites] = useState<Set<string>>(new Set());
  const [answered, setAnswered] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState<Filter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // mốc "đã xem" lúc mở trang: giữ để tô chấm chưa đọc trong lần xem này
  const [seenAt] = useState(() => { try { return localStorage.getItem(SEEN_KEY) || ''; } catch { return ''; } });

  const load = async (markRead: boolean) => {
    setLoading(true); setError(null);
    try {
      const [n, a, inv] = await Promise.all([getNotifications(), getActivity(60), myInvites().catch(() => [])]);
      setOrg(n.items); setActs(a); setOpenInvites(new Set(inv.map(i => i.invite_id)));
      if (markRead) {
        if (n.unread) await markNotificationsRead('all').catch(() => undefined);
        try { localStorage.setItem(SEEN_KEY, a[0]?.created_at || new Date().toISOString()); } catch { /* chế độ riêng tư */ }
        window.dispatchEvent(new Event('oq-notif-read'));  // chuông trên cụm góc phải về 0
      }
    } catch (e: any) { setError(e.message || 'Không tải được thông báo.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(true); }, []);

  const items = useMemo<Item[]>(() => [
    ...org.map(n => ({ id: n.notification_id, kind: 'org' as const, ...orgKind(n), at: serverDate(n.created_at), unread: !n.read,
      title: orgNoteText(n, orgTerms(workspaces.find(w => w.id === n.space_id))), invite: n.kind === 'invite' ? n.payload.invite_id : undefined })),
    ...acts.map((a, i) => ({ id: `a${i}-${a.created_at}`, kind: 'activity' as const, Icon: a.status >= 400 ? AlertTriangle : noteIcon(a.action), at: serverDate(a.created_at),
      unread: !!seenAt ? a.created_at > seenAt : false, bad: a.status >= 400, title: a.action, sub: a.target && !RAW_ID.test(a.target) ? a.target : undefined })),
  ].sort((x, y) => y.at.getTime() - x.at.getTime()), [org, acts, workspaces, seenAt]);

  const pendingInvites = items.filter(i => i.invite && openInvites.has(i.invite) && !answered[i.invite]).length;
  const counts: Record<Filter, number> = { all: items.length, unread: items.filter(i => i.unread).length, org: items.filter(i => i.kind === 'org').length, activity: items.filter(i => i.kind === 'activity').length };
  const shown = items.filter(i => filter === 'all' || (filter === 'unread' ? i.unread : i.kind === filter));
  const groups = shown.reduce<[string, Item[]][]>((acc, it) => {
    const g = dayGroup(it.at); const last = acc[acc.length - 1];
    if (last && last[0] === g) last[1].push(it); else acc.push([g, [it]]);
    return acc;
  }, []);

  const answer = async (invite: string, decision: 'accept' | 'decline') => {
    try { await answerInvite(invite, decision); setAnswered(a => ({ ...a, [invite]: decision === 'accept' ? 'Đã tham gia' : 'Đã từ chối' })); onOrgChanged?.(); }
    catch (e: any) { setAnswered(a => ({ ...a, [invite]: e.message })); }
  };

  return (
    <main className="pg tl tone-overview nt">
      <div className="pg-col">
        <ToolHeader Icon={Bell} title="Thông báo" desc="Lời mời, duyệt và thay đổi trong tổ chức cùng các hoạt động gần đây của tài khoản."
          right={<button type="button" className="btn btn-ghost is-sm" onClick={() => void load(false)} disabled={loading}><RefreshCw size={14} className={loading ? 'nt-spin' : ''} />Làm mới</button>} />

        <section className="nt-stats" aria-label="Tóm tắt">
          <div className={counts.unread ? 'is-hot' : ''}><span className="nt-stat-ico"><Bell size={18} /></span><b>{counts.unread}</b><small>mới kể từ lần xem trước</small></div>
          <div><span className="nt-stat-ico"><MailPlus size={18} /></span><b>{pendingInvites}</b><small>lời mời đang chờ bạn</small></div>
          <div><span className="nt-stat-ico"><AlertTriangle size={18} /></span><b>{items.filter(i => i.bad).length}</b><small>thao tác không thành công</small></div>
        </section>

        <section className="dz-card nt-card">
          <div className="nt-bar">
            <div className="nt-tabs" role="tablist" aria-label="Lọc thông báo">
              {([['all', 'Tất cả'], ['unread', 'Mới'], ['org', 'Tổ chức & tài liệu'], ['activity', 'Hoạt động']] as [Filter, string][]).map(([k, l]) =>
                <button key={k} type="button" role="tab" aria-selected={filter === k} className={filter === k ? 'is-on' : ''} onClick={() => setFilter(k)}>{l}<i>{counts[k]}</i></button>)}
            </div>
            <span className="nt-note"><CheckCheck size={14} />Đã đánh dấu đã đọc khi mở trang</span>
          </div>

          {error && <p className="note is-error" role="alert">{error}</p>}
          {loading && items.length === 0 ? <div className="nt-skel" aria-hidden="true">{[0, 1, 2, 3].map(i => <i key={i} />)}</div>
            : shown.length === 0 ? <div className="nt-empty"><span>{filter === 'unread' ? <BellOff size={26} /> : <Inbox size={26} />}</span>
              <b>{filter === 'unread' ? 'Không có gì mới' : 'Chưa có thông báo'}</b><p>{filter === 'unread' ? 'Bạn đã xem hết thông báo.' : 'Lời mời vào tổ chức và hoạt động của bạn sẽ hiện ở đây.'}</p></div>
            : groups.map(([g, list]) => <div key={g} className="nt-group">
              <h2>{g}</h2>
              <ul>{list.map(it => {
                const done = it.invite ? (answered[it.invite] ?? (openInvites.has(it.invite) ? null : 'Đã xử lý')) : null;
                return <li key={it.id} className={`nt-item${it.unread ? ' is-unread' : ''}${it.bad ? ' is-bad' : ''}`}>
                  <span className={`nt-ico is-${it.kind}`}><it.Icon size={17} /></span>
                  <div className="nt-body">
                    <b>{it.title}</b>
                    <small>{it.sub && <span>{it.sub}</span>}<time dateTime={it.at.toISOString()}>{ago(it.at)}</time></small>
                    {it.invite && (done ? <em className="nt-done">{done}</em> : <span className="nt-acts">
                      <button type="button" className="btn btn-dark is-sm" onClick={() => answer(it.invite!, 'accept')}>Tham gia</button>
                      <button type="button" className="btn btn-ghost is-sm" onClick={() => answer(it.invite!, 'decline')}>Từ chối</button></span>)}
                  </div>
                  {it.go && <button type="button" className="dp-link nt-go" onClick={() => onGo(it.go!)}>{it.go === 'consistency' ? 'Kiểm tra' : 'Mở'}</button>}
                  {it.unread && <i className="nt-dot" aria-label="Mới" />}
                </li>;
              })}</ul>
            </div>)}
          {counts.activity > 0 && <button type="button" className="dp-link nt-more" onClick={() => onGo('overview')}>Xem toàn bộ nhật ký hoạt động ở trang Tổng quan</button>}
        </section>
      </div>
    </main>
  );
};
