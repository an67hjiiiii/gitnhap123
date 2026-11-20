// Thanh trên cùng (Đợt 1, khung mới 20/11): tên trang + mô tả, chọn không gian, Lịch sử trò chuyện, thông báo, trợ giúp,
// menu ảnh đại diện (Cài đặt, giao diện sáng/tối, đăng xuất). Thanh bên giờ chỉ để điều hướng.
import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, Bell, Building2, Check, ChevronsUpDown, CircleHelp, FileText, History, ImageUp, LogOut, Menu, MessagesSquare, Palette, Plus, Search, Settings2, Sun, Moon, Trash2, UserCheck, X } from 'lucide-react';
import { NavigationTab, User, Workspace } from '../types';
import { ActivityRow, answerInvite, DOMAIN_PACKS, DomainPack, getActivity, getNotifications, markNotificationsRead, myInvites, OrgNotification, orgTerms } from '../services/api';
import { noteIcon, orgNoteText, useDismiss } from './Header';
import { Avatar, AvatarDialog } from './Avatar';
import { StudioModal } from './StudioModal';
import { pageMeta } from '../utils/pageMeta';
import { NAV_ICONS } from './NavIcons';

// trang con dùng biểu tượng của mục cha
const ICON_OF: Partial<Record<NavigationTab, string>> = { documents: 'library', consistency: 'library', tasks: 'results' };

const fold = (v: string) => v.normalize('NFD').replace(/\p{M}/gu, '').replace(/đ/gi, 'd').toLowerCase();
const ROLE_LABEL: Record<string, string> = { tech_lead: 'Trưởng nhóm', researcher: 'Nghiên cứu', developer: 'Người dùng', admin: 'Quản trị' };

// ô của không gian: cá nhân 6 kiểu cùng họ xanh lam theo thứ tự tạo; tổ chức tím chàm
export const WsTile: React.FC<{ ws: Workspace; className?: string; variant?: number }> = ({ ws, className = 'wsp-tile', variant = 0 }) => {
  const words = ws.name.trim().split(/\s+/).filter(w => /^\p{L}|^\d/u.test(w));
  const text = ((words[0]?.[0] ?? '?') + (words[1]?.[0] ?? '')).toUpperCase();
  return <span className={`${className} wsp-hue${ws.kind === 'org' ? ' is-org' : ''}`} data-v={ws.kind === 'org' ? undefined : variant % 6} aria-hidden="true">
    {ws.kind === 'org' ? <Building2 size={15} strokeWidth={2.2} /> : text}</span>;
};

function ago(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').getTime()) / 1000);
  if (s < 60) return 'vừa xong';
  if (s < 3600) return `${Math.floor(s / 60)} phút`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ`;
  return `${Math.floor(s / 86400)} ngày`;
}

interface TopbarProps {
  activeTab: NavigationTab;
  onTabChange: (tab: NavigationTab) => void;
  user: User | null;
  workspaces: Workspace[];
  currentWorkspaceId: number | string;
  onWorkspaceChange: (wsId: number | string) => void;
  onCreateWorkspace?: (name: string, description: string, pack: DomainPack) => Promise<void>;
  onDeleteWorkspace?: (wsId: number | string, deleteSources: boolean) => Promise<void>;
  onLogout: () => void;
  onUserChange?: (u: User) => void;
  theme?: 'light' | 'dark';
  onThemeChange?: (t: 'light' | 'dark', at?: { x: number; y: number }) => void;
  onOpenPalette?: () => void;
  /** điện thoại: mở thanh bên (ngăn kéo) */
  onOpenMenu: () => void;
  menuOpen?: boolean;
  onOrgChanged?: () => void;
  /** nội dung ngăn kéo Lịch sử trò chuyện */
  history?: React.ReactNode;
  historyOpen: boolean;
  /** vị trí đặt (20/11: bỏ thanh trên): 'top' = chọn không gian ở đầu thanh bên; 'bottom' = tài khoản, lịch sử,
   *  thông báo, trợ giúp ở chân thanh bên; 'mobile' = dải mỏng trên điện thoại (nút menu, tên trang, lịch sử) */
  slot: 'top' | 'bottom' | 'mobile' | 'cluster';
  onHistoryOpen: (open: boolean) => void;
}

export const Topbar: React.FC<TopbarProps> = ({
  activeTab, onTabChange, user, workspaces, currentWorkspaceId, onWorkspaceChange, onCreateWorkspace, onDeleteWorkspace, onLogout, onUserChange,
  theme = 'light', onThemeChange, onOpenPalette, onOpenMenu, menuOpen, onOrgChanged, history, historyOpen, onHistoryOpen, slot,
}) => {
  const [menu, setMenu] = useState<'ws' | 'profile' | 'notif' | 'help' | null>(null);
  const closeMenu = React.useCallback(() => setMenu(null), []);
  const wsRef = useDismiss(menu === 'ws', closeMenu);
  const notifRef = useDismiss(menu === 'notif', closeMenu);
  const helpRef = useDismiss(menu === 'help', closeMenu);
  const profileRef = useDismiss(menu === 'profile', closeMenu);
  const [avatarOpen, setAvatarOpen] = useState(false);
  useEffect(() => {
    if (slot !== 'bottom' && slot !== 'cluster') return;
    const open = () => setAvatarOpen(true);  // trang Cài đặt mở hộp đổi ảnh đại diện
    window.addEventListener('oq-open-avatar', open);
    return () => window.removeEventListener('oq-open-avatar', open);
  }, []);
  const meta = pageMeta(activeTab);
  const current = workspaces.find(w => w.id === currentWorkspaceId) || workspaces[0];

  // ---- chọn không gian ----
  const [wsQuery, setWsQuery] = useState('');
  useEffect(() => { if (menu !== 'ws') setWsQuery(''); }, [menu]);
  const wsVariant = React.useMemo(() => new Map(workspaces.filter(w => w.kind !== 'org')
    .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)) || String(a.id).localeCompare(String(b.id)))
    .map((w, i) => [w.id, i])), [workspaces]);
  const [wsToDelete, setWsToDelete] = useState<Workspace | null>(null);
  const [deleteDocs, setDeleteDocs] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [newWs, setNewWs] = useState({ name: '', desc: '', pack: 'general' as DomainPack });
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const submitCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWs.name.trim()) { setCreateError('Vui lòng nhập tên không gian làm việc.'); return; }
    if (!onCreateWorkspace) return;
    setCreating(true); setCreateError(null);
    try { await onCreateWorkspace(newWs.name.trim(), newWs.desc.trim(), newWs.pack); setNewWs({ name: '', desc: '', pack: 'general' }); setCreateOpen(false); }
    catch (err: any) { setCreateError(err.message || 'Không thể tạo không gian làm việc mới.'); }
    finally { setCreating(false); }
  };

  // ---- thông báo: hoạt động thật của tài khoản + thông báo tổ chức ----
  const [notes, setNotes] = useState<ActivityRow[]>([]);
  const [seenAt, setSeenAt] = useState(() => { try { return localStorage.getItem('orchestriq-notif-seen') || ''; } catch { return ''; } });
  useEffect(() => {
    if (!user || (slot !== 'bottom' && slot !== 'cluster')) return;
    let alive = true;
    const load = () => getActivity(8).then(r => alive && setNotes(r)).catch(() => undefined);
    load(); const t = window.setInterval(() => { if (!document.hidden) load(); }, 60000);
    return () => { alive = false; window.clearInterval(t); };
  }, [user?.username]);
  const [orgNotes, setOrgNotes] = useState<OrgNotification[]>([]);
  const [orgUnread, setOrgUnread] = useState(0);
  const [openInvites, setOpenInvites] = useState<Set<string>>(new Set());
  const loadOrg = () => Promise.all([getNotifications(), myInvites().catch(() => [])]).then(([r, inv]) => {
    setOrgNotes(r.items.slice(0, 8)); setOrgUnread(r.unread); setOpenInvites(new Set(inv.map(i => i.invite_id)));
  }).catch(() => undefined);
  useEffect(() => {
    if (!user || (slot !== 'bottom' && slot !== 'cluster')) return;
    void loadOrg(); const t = window.setInterval(() => { if (!document.hidden) void loadOrg(); }, 30000);
    return () => window.clearInterval(t);
  }, [user?.username]);
  const [answered, setAnswered] = useState<Record<string, string>>({});
  const answer = async (invite: string, decision: 'accept' | 'decline') => {
    try { await answerInvite(invite, decision); setAnswered(a => ({ ...a, [invite]: decision === 'accept' ? 'Đã tham gia' : 'Đã từ chối' })); onOrgChanged?.(); }
    catch (e: any) { setAnswered(a => ({ ...a, [invite]: e.message })); }
  };
  const unread = notes.filter(n => !seenAt || n.created_at > seenAt).length + orgUnread;
  const openNotif = () => {
    const next = menu === 'notif' ? null : 'notif';
    setMenu(next);
    if (next && orgUnread) { setOrgUnread(0); markNotificationsRead('all').catch(() => undefined); }
    if (next) { getActivity(8).then(setNotes).catch(() => undefined); const now = notes[0]?.created_at || new Date().toISOString(); setSeenAt(now); try { localStorage.setItem('orchestriq-notif-seen', now); } catch { /* chế độ riêng tư */ } }
  };
  const go = (tab: NavigationTab) => { setMenu(null); onTabChange(tab); };

  // ngăn kéo Lịch sử: Esc để đóng, trả tiêu điểm về nút
  const histBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!historyOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { onHistoryOpen(false); histBtn.current?.focus(); } };
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey);
  }, [historyOpen]);

  return (
    <>
      {slot === 'mobile' && <header className="st-mobilehead" aria-label="Thanh trên cùng (điện thoại)">
        <button className="tb-btn tb-menu" onClick={onOpenMenu} aria-label="Mở thanh điều hướng" aria-expanded={!!menuOpen}><Menu size={20} /></button>
        <b className="mh-title">{meta.title}</b>
                  {user && history && <button ref={histBtn} className={`tb-btn${historyOpen ? ' is-on' : ''}`} onClick={() => onHistoryOpen(!historyOpen)} aria-expanded={historyOpen} aria-controls="tb-history" aria-label="Lịch sử trò chuyện" title="Lịch sử trò chuyện">
            <History size={18} /></button>}

      </header>}
      {slot === 'top' && <div className="sb-wsbox">
          {user && <div className="tb-pop" ref={wsRef}>
            <button className="tb-ws" onClick={() => setMenu(menu === 'ws' ? null : 'ws')} aria-expanded={menu === 'ws'} aria-haspopup="menu" title="Chuyển không gian làm việc">
              {current ? <WsTile ws={current} className="tb-ws-mark" variant={wsVariant.get(current.id)} /> : <span className="tb-ws-mark">?</span>}
              <span className="tb-ws-text"><small>{current?.kind === 'org' ? 'Tổ chức' : 'Cá nhân'}</small><b>{current?.name || 'Chưa chọn không gian'}</b></span>
              <ChevronsUpDown size={14} />
            </button>
            {menu === 'ws' && (() => {
              const q = fold(wsQuery.trim());
              const shown = q ? workspaces.filter(w => fold(w.name).includes(q)) : workspaces;
              const canDelete = !!onDeleteWorkspace && workspaces.filter(w => w.kind !== 'org').length > 1;
              const groups = [['Cá nhân', shown.filter(w => w.kind !== 'org')], ['Tổ chức', shown.filter(w => w.kind === 'org')]] as const;
              return <div className="pop tb-drop wsp-pop" role="menu" aria-label="Không gian làm việc">
                <div className="wsp-pop-head"><b>Không gian làm việc</b><span className="wsp-count">{workspaces.length}</span></div>
                {workspaces.length >= 5 && <label className="wsp-find"><Search size={14} />
                  <input autoFocus value={wsQuery} onChange={e => setWsQuery(e.target.value)} placeholder="Tìm không gian…" aria-label="Tìm không gian" /></label>}
                <div className="pop-scroll wsp-list">
                  {shown.length === 0 && <p className="wsp-empty">Không có không gian nào khớp “{wsQuery}”.</p>}
                  {groups.map(([title, list]) => list.length > 0 && <div key={title} className="wsp-group">
                    <p className="wsp-group-t">{title}</p>
                    {list.map(ws => {
                      const on = ws.id === currentWorkspaceId;
                      return <div key={ws.id} className={`wsp-item${on ? ' is-on' : ''}`}>
                        <button role="menuitemradio" aria-checked={on} className="wsp-pick" onClick={() => { onWorkspaceChange(ws.id); setMenu(null); }}>
                          <WsTile ws={ws} variant={wsVariant.get(ws.id)} />
                          <span className="wsp-info"><b>{ws.name}</b>
                            <span className="wsp-meta">{ws.kind === 'org'
                              ? <i className="wsp-role">{ws.level ? orgTerms(ws).level[ws.level] : 'Thành viên'}{ws.is_owner ? ' · Chủ' : ''}</i>
                              : <><i title="Tài liệu"><FileText size={12} />{ws.documents_count}</i><i title="Cuộc trò chuyện"><MessagesSquare size={12} />{ws.runs_count}</i></>}</span>
                          </span>
                          {on && <span className="wsp-now"><Check size={12} strokeWidth={3} />Đang mở</span>}
                        </button>
                        {canDelete && ws.kind !== 'org' && <button className="wsp-del" aria-label={`Xóa không gian ${ws.name}`} title="Xóa không gian"
                          onClick={() => { setMenu(null); setDeleteDocs(false); setWsToDelete(ws); }}><Trash2 size={14} /></button>}
                      </div>;
                    })}
                  </div>)}
                </div>
                {onCreateWorkspace && <button className="wsp-new" onClick={() => { setMenu(null); setCreateOpen(true); }}>
                  <span className="wsp-new-ico"><Plus size={16} strokeWidth={2.4} /></span><span className="wsp-info"><b>Tạo không gian mới</b><small>Kho tài liệu và lịch sử trò chuyện riêng</small></span></button>}
                <button className="wsp-new" onClick={() => go('organization')}>
                  <span className="wsp-new-ico"><Building2 size={16} strokeWidth={2.2} /></span><span className="wsp-info"><b>Tạo hoặc tham gia tổ chức</b><small>Chia sẻ tài liệu theo cấp bậc, mức mật</small></span></button>
              </div>;
            })()}
          </div>}

      </div>}
      {slot === 'cluster' && <div className="st-cluster" aria-label="Không gian và tài khoản">
          {user && <div className="tb-pop" ref={wsRef}>
            <button className="tb-ws" onClick={() => setMenu(menu === 'ws' ? null : 'ws')} aria-expanded={menu === 'ws'} aria-haspopup="menu" title="Chuyển không gian làm việc">
              {current ? <WsTile ws={current} className="tb-ws-mark" variant={wsVariant.get(current.id)} /> : <span className="tb-ws-mark">?</span>}
              <span className="tb-ws-text"><small>{current?.kind === 'org' ? 'Tổ chức' : 'Cá nhân'}</small><b>{current?.name || 'Chưa chọn không gian'}</b></span>
              <ChevronsUpDown size={14} />
            </button>
            {menu === 'ws' && (() => {
              const q = fold(wsQuery.trim());
              const shown = q ? workspaces.filter(w => fold(w.name).includes(q)) : workspaces;
              const canDelete = !!onDeleteWorkspace && workspaces.filter(w => w.kind !== 'org').length > 1;
              const groups = [['Cá nhân', shown.filter(w => w.kind !== 'org')], ['Tổ chức', shown.filter(w => w.kind === 'org')]] as const;
              return <div className="pop tb-drop wsp-pop" role="menu" aria-label="Không gian làm việc">
                <div className="wsp-pop-head"><b>Không gian làm việc</b><span className="wsp-count">{workspaces.length}</span></div>
                {workspaces.length >= 5 && <label className="wsp-find"><Search size={14} />
                  <input autoFocus value={wsQuery} onChange={e => setWsQuery(e.target.value)} placeholder="Tìm không gian…" aria-label="Tìm không gian" /></label>}
                <div className="pop-scroll wsp-list">
                  {shown.length === 0 && <p className="wsp-empty">Không có không gian nào khớp “{wsQuery}”.</p>}
                  {groups.map(([title, list]) => list.length > 0 && <div key={title} className="wsp-group">
                    <p className="wsp-group-t">{title}</p>
                    {list.map(ws => {
                      const on = ws.id === currentWorkspaceId;
                      return <div key={ws.id} className={`wsp-item${on ? ' is-on' : ''}`}>
                        <button role="menuitemradio" aria-checked={on} className="wsp-pick" onClick={() => { onWorkspaceChange(ws.id); setMenu(null); }}>
                          <WsTile ws={ws} variant={wsVariant.get(ws.id)} />
                          <span className="wsp-info"><b>{ws.name}</b>
                            <span className="wsp-meta">{ws.kind === 'org'
                              ? <i className="wsp-role">{ws.level ? orgTerms(ws).level[ws.level] : 'Thành viên'}{ws.is_owner ? ' · Chủ' : ''}</i>
                              : <><i title="Tài liệu"><FileText size={12} />{ws.documents_count}</i><i title="Cuộc trò chuyện"><MessagesSquare size={12} />{ws.runs_count}</i></>}</span>
                          </span>
                          {on && <span className="wsp-now"><Check size={12} strokeWidth={3} />Đang mở</span>}
                        </button>
                        {canDelete && ws.kind !== 'org' && <button className="wsp-del" aria-label={`Xóa không gian ${ws.name}`} title="Xóa không gian"
                          onClick={() => { setMenu(null); setDeleteDocs(false); setWsToDelete(ws); }}><Trash2 size={14} /></button>}
                      </div>;
                    })}
                  </div>)}
                </div>
                {onCreateWorkspace && <button className="wsp-new" onClick={() => { setMenu(null); setCreateOpen(true); }}>
                  <span className="wsp-new-ico"><Plus size={16} strokeWidth={2.4} /></span><span className="wsp-info"><b>Tạo không gian mới</b><small>Kho tài liệu và lịch sử trò chuyện riêng</small></span></button>}
                <button className="wsp-new" onClick={() => go('organization')}>
                  <span className="wsp-new-ico"><Building2 size={16} strokeWidth={2.2} /></span><span className="wsp-info"><b>Tạo hoặc tham gia tổ chức</b><small>Chia sẻ tài liệu theo cấp bậc, mức mật</small></span></button>
              </div>;
            })()}
          </div>}

          {user && history && <button ref={histBtn} className={`tb-btn${historyOpen ? ' is-on' : ''}`} onClick={() => onHistoryOpen(!historyOpen)} aria-expanded={historyOpen} aria-controls="tb-history" aria-label="Lịch sử trò chuyện" title="Lịch sử trò chuyện">
            <History size={18} /><span className="tb-btn-t">Lịch sử</span></button>}

          {user && <div className="tb-pop" ref={notifRef}>
            <button type="button" className="tb-btn" onClick={openNotif} aria-expanded={menu === 'notif'} aria-haspopup="dialog" aria-label={unread ? `Thông báo, ${unread} mục mới` : 'Thông báo'} title="Thông báo">
              <Bell size={18} />{unread > 0 && <i className="sb-badge">{unread > 9 ? '9+' : unread}</i>}
            </button>
            {menu === 'notif' && <div className="pop tb-drop sb-notif" role="dialog" aria-label="Hoạt động gần đây">
              {orgNotes.length > 0 && <><div className="sb-notif-head"><b>Tổ chức</b><button type="button" className="dp-link" onClick={() => go('organization')}>Mở trang Tổ chức</button></div>
              <ul className="og-notes">{orgNotes.map(n => <li key={n.notification_id} className={n.read ? '' : 'is-unread'}>
                <span className="sb-notif-ico"><Building2 size={15} /></span>
                <span className="sb-notif-t"><b>{orgNoteText(n, orgTerms(workspaces.find(w => w.id === n.space_id)))}</b>
                  {n.kind === 'invite' && n.payload.invite_id && (answered[n.payload.invite_id] || !openInvites.has(n.payload.invite_id)
                    ? <small>{answered[n.payload.invite_id] ?? 'Đã xử lý'}</small>
                    : <span className="og-note-acts"><button type="button" className="btn btn-dark is-sm" onClick={() => answer(n.payload.invite_id, 'accept')}>Tham gia</button>
                      <button type="button" className="btn btn-ghost is-sm" onClick={() => answer(n.payload.invite_id, 'decline')}>Từ chối</button></span>)}</span>
                <time>{ago(n.created_at)}</time></li>)}</ul></>}
              <div className="sb-notif-head"><b>Hoạt động gần đây</b><button type="button" className="dp-link" onClick={() => go('overview')}>Xem tất cả</button></div>
              {notes.length === 0 ? <p className="sb-notif-empty">Chưa có hoạt động nào.</p> : <ul>{notes.map((n, i) => {
                const I = noteIcon(n.action);
                return <li key={i} className={n.status >= 400 ? 'is-bad' : ''}><span className="sb-notif-ico"><I size={15} /></span>
                  <span className="sb-notif-t"><b>{n.action}</b>{n.target && !/^(usr|sp|src|inv|shr|dep|rs|rpt|ws)_[A-Za-z0-9_-]+$/.test(n.target) && <small>{n.target}</small>}</span><time>{ago(n.created_at)}</time></li>;
              })}</ul>}
            </div>}
          </div>}

          <div className="tb-pop tb-help-wrap" ref={helpRef}>
            <button type="button" className="tb-btn" onClick={() => setMenu(menu === 'help' ? null : 'help')} aria-expanded={menu === 'help'} aria-haspopup="dialog" aria-label="Trợ giúp" title="Trợ giúp"><CircleHelp size={18} /></button>
            {menu === 'help' && <div className="pop tb-drop tb-help" role="dialog" aria-label="Trợ giúp">
              <b>{meta.title}</b><p>{meta.desc}</p>
              <ul>
                <li><kbd>Ctrl K</kbd>Tìm nhanh và chuyển trang</li>
                <li><kbd>/</kbd>Trong ô chat: chọn kỹ năng</li>
                <li><kbd>Ctrl B</kbd>Thu gọn thanh bên</li>
              </ul>
              {onOpenPalette && <button type="button" className="btn btn-ghost is-sm" onClick={() => { setMenu(null); onOpenPalette(); }}><Search size={14} />Mở tìm nhanh</button>}
            </div>}
          </div>

          {user ? <div className="tb-pop" ref={profileRef}>
            <button className="tb-user" onClick={() => setMenu(menu === 'profile' ? null : 'profile')} aria-expanded={menu === 'profile'} aria-haspopup="menu" aria-label={`Tài khoản ${user.full_name}`}>
              <Avatar value={user.avatar} className="sb-avatar">{user.full_name.charAt(0)}</Avatar>
              <span className="tb-user-text"><b>{user.full_name}</b><small>{ROLE_LABEL[user.role] ?? user.role}</small></span>
            </button>
            {menu === 'profile' && <div className="pop tb-drop tb-profile" role="menu">
              <div className="sb-me"><Avatar value={user.avatar} className="sb-avatar is-lg">{user.full_name.charAt(0)}</Avatar><span><b>{user.full_name}</b><small>{user.username} · {ROLE_LABEL[user.role] ?? user.role}</small></span></div>
              {onThemeChange && <div className="sb-set"><span><Palette size={15} />Giao diện</span>
                <span className="sb-seg" role="group" aria-label="Chọn giao diện">
                  <button type="button" aria-pressed={theme === 'light'} onClick={e => onThemeChange('light', { x: e.clientX, y: e.clientY })}><Sun size={13} />Sáng</button>
                  <button type="button" aria-pressed={theme === 'dark'} onClick={e => onThemeChange('dark', { x: e.clientX, y: e.clientY })}><Moon size={13} />Tối</button>
                </span></div>}
              <button role="menuitem" className="pop-item" onClick={() => go('settings')}><Settings2 size={15} />Cài đặt</button>
              {onUserChange && <button role="menuitem" className="pop-item" onClick={() => { setMenu(null); setAvatarOpen(true); }}><ImageUp size={15} />Đổi ảnh đại diện</button>}
              <div className="pop-sep" />
              <Link to="/login" role="menuitem" className="pop-item" onClick={() => setMenu(null)}><UserCheck size={15} />Đổi tài khoản</Link>
              <button role="menuitem" className="pop-item is-danger" onClick={() => { setMenu(null); onLogout(); }}><LogOut size={15} />Đăng xuất</button>
            </div>}
          </div> : <Link to="/login" className="btn btn-dark is-sm">Đăng nhập</Link>}
      </div>}
      {slot === 'bottom' && <div className="sb-account">
          {user ? <div className="tb-pop" ref={profileRef}>
            <button className="tb-user" onClick={() => setMenu(menu === 'profile' ? null : 'profile')} aria-expanded={menu === 'profile'} aria-haspopup="menu" aria-label={`Tài khoản ${user.full_name}`}>
              <Avatar value={user.avatar} className="sb-avatar">{user.full_name.charAt(0)}</Avatar>
              <span className="tb-user-text"><b>{user.full_name}</b><small>{ROLE_LABEL[user.role] ?? user.role}</small></span>
            </button>
            {menu === 'profile' && <div className="pop tb-drop tb-profile" role="menu">
              <div className="sb-me"><Avatar value={user.avatar} className="sb-avatar is-lg">{user.full_name.charAt(0)}</Avatar><span><b>{user.full_name}</b><small>{user.username} · {ROLE_LABEL[user.role] ?? user.role}</small></span></div>
              {onThemeChange && <div className="sb-set"><span><Palette size={15} />Giao diện</span>
                <span className="sb-seg" role="group" aria-label="Chọn giao diện">
                  <button type="button" aria-pressed={theme === 'light'} onClick={e => onThemeChange('light', { x: e.clientX, y: e.clientY })}><Sun size={13} />Sáng</button>
                  <button type="button" aria-pressed={theme === 'dark'} onClick={e => onThemeChange('dark', { x: e.clientX, y: e.clientY })}><Moon size={13} />Tối</button>
                </span></div>}
              <button role="menuitem" className="pop-item" onClick={() => go('settings')}><Settings2 size={15} />Cài đặt</button>
              {onUserChange && <button role="menuitem" className="pop-item" onClick={() => { setMenu(null); setAvatarOpen(true); }}><ImageUp size={15} />Đổi ảnh đại diện</button>}
              <div className="pop-sep" />
              <Link to="/login" role="menuitem" className="pop-item" onClick={() => setMenu(null)}><UserCheck size={15} />Đổi tài khoản</Link>
              <button role="menuitem" className="pop-item is-danger" onClick={() => { setMenu(null); onLogout(); }}><LogOut size={15} />Đăng xuất</button>
            </div>}
          </div> : <Link to="/login" className="btn btn-dark is-sm">Đăng nhập</Link>}
        <div className="sb-account-tools">
          {user && history && <button ref={histBtn} className={`tb-btn${historyOpen ? ' is-on' : ''}`} onClick={() => onHistoryOpen(!historyOpen)} aria-expanded={historyOpen} aria-controls="tb-history" aria-label="Lịch sử trò chuyện" title="Lịch sử trò chuyện">
            <History size={18} /><span className="tb-btn-t">Lịch sử</span></button>}

          {user && <div className="tb-pop" ref={notifRef}>
            <button type="button" className="tb-btn" onClick={openNotif} aria-expanded={menu === 'notif'} aria-haspopup="dialog" aria-label={unread ? `Thông báo, ${unread} mục mới` : 'Thông báo'} title="Thông báo">
              <Bell size={18} />{unread > 0 && <i className="sb-badge">{unread > 9 ? '9+' : unread}</i>}
            </button>
            {menu === 'notif' && <div className="pop tb-drop sb-notif" role="dialog" aria-label="Hoạt động gần đây">
              {orgNotes.length > 0 && <><div className="sb-notif-head"><b>Tổ chức</b><button type="button" className="dp-link" onClick={() => go('organization')}>Mở trang Tổ chức</button></div>
              <ul className="og-notes">{orgNotes.map(n => <li key={n.notification_id} className={n.read ? '' : 'is-unread'}>
                <span className="sb-notif-ico"><Building2 size={15} /></span>
                <span className="sb-notif-t"><b>{orgNoteText(n, orgTerms(workspaces.find(w => w.id === n.space_id)))}</b>
                  {n.kind === 'invite' && n.payload.invite_id && (answered[n.payload.invite_id] || !openInvites.has(n.payload.invite_id)
                    ? <small>{answered[n.payload.invite_id] ?? 'Đã xử lý'}</small>
                    : <span className="og-note-acts"><button type="button" className="btn btn-dark is-sm" onClick={() => answer(n.payload.invite_id, 'accept')}>Tham gia</button>
                      <button type="button" className="btn btn-ghost is-sm" onClick={() => answer(n.payload.invite_id, 'decline')}>Từ chối</button></span>)}</span>
                <time>{ago(n.created_at)}</time></li>)}</ul></>}
              <div className="sb-notif-head"><b>Hoạt động gần đây</b><button type="button" className="dp-link" onClick={() => go('overview')}>Xem tất cả</button></div>
              {notes.length === 0 ? <p className="sb-notif-empty">Chưa có hoạt động nào.</p> : <ul>{notes.map((n, i) => {
                const I = noteIcon(n.action);
                return <li key={i} className={n.status >= 400 ? 'is-bad' : ''}><span className="sb-notif-ico"><I size={15} /></span>
                  <span className="sb-notif-t"><b>{n.action}</b>{n.target && !/^(usr|sp|src|inv|shr|dep|rs|rpt|ws)_[A-Za-z0-9_-]+$/.test(n.target) && <small>{n.target}</small>}</span><time>{ago(n.created_at)}</time></li>;
              })}</ul>}
            </div>}
          </div>}

          <div className="tb-pop tb-help-wrap" ref={helpRef}>
            <button type="button" className="tb-btn" onClick={() => setMenu(menu === 'help' ? null : 'help')} aria-expanded={menu === 'help'} aria-haspopup="dialog" aria-label="Trợ giúp" title="Trợ giúp"><CircleHelp size={18} /></button>
            {menu === 'help' && <div className="pop tb-drop tb-help" role="dialog" aria-label="Trợ giúp">
              <b>{meta.title}</b><p>{meta.desc}</p>
              <ul>
                <li><kbd>Ctrl K</kbd>Tìm nhanh và chuyển trang</li>
                <li><kbd>/</kbd>Trong ô chat: chọn kỹ năng</li>
                <li><kbd>Ctrl B</kbd>Thu gọn thanh bên</li>
              </ul>
              {onOpenPalette && <button type="button" className="btn btn-ghost is-sm" onClick={() => { setMenu(null); onOpenPalette(); }}><Search size={14} />Mở tìm nhanh</button>}
            </div>}
          </div>

        </div>
      </div>}

      {(slot === 'bottom' || slot === 'cluster') && historyOpen && history && <>
        <div className="tb-scrim" onClick={() => onHistoryOpen(false)} />
        <aside id="tb-history" className="tb-history" aria-label="Lịch sử trò chuyện">
          <div className="tb-history-head"><b><History size={16} />Lịch sử trò chuyện</b>
            <button className="tb-btn" onClick={() => { onHistoryOpen(false); histBtn.current?.focus(); }} aria-label="Đóng lịch sử"><X size={18} /></button></div>
          {history}
        </aside>
      </>}

      {(slot === 'bottom' || slot === 'cluster') && avatarOpen && user && onUserChange && <AvatarDialog user={user} onClose={() => setAvatarOpen(false)} onSaved={onUserChange} />}

      {(slot === 'top' || slot === 'cluster') && wsToDelete && onDeleteWorkspace && (
        <StudioModal labelId="ws-del-title" size="md" icon={<Trash2 size={18} />} title={`Xóa không gian "${wsToDelete.name}"?`}
          subtitle="Cuộc trò chuyện được chuyển sang không gian còn lại." onClose={() => setWsToDelete(null)}
          footer={<>
            <button className="btn btn-ghost" onClick={() => setWsToDelete(null)}>Hủy</button>
            <button className="btn btn-danger" disabled={deleting} onClick={async () => {
              setDeleting(true);
              try { await onDeleteWorkspace(wsToDelete.id, deleteDocs); setWsToDelete(null); } finally { setDeleting(false); }
            }}>{deleting ? 'Đang xóa…' : 'Xóa không gian'}</button>
          </>}>
          <label className="ws-del-opt">
            <input type="checkbox" checked={deleteDocs} onChange={e => setDeleteDocs(e.target.checked)} data-autofocus />
            <span><b>Xóa luôn {wsToDelete.documents_count} tài liệu</b> trong không gian này. Không chọn thì tài liệu được chuyển sang không gian còn lại.</span>
          </label>
        </StudioModal>
      )}

      {(slot === 'top' || slot === 'cluster') && createOpen && (
        <StudioModal labelId="workspace-dialog-title" size="md" icon={<Plus size={18} />} title="Tạo không gian làm việc"
          subtitle="Mỗi không gian có kho tài liệu và lịch sử trò chuyện riêng." onClose={() => setCreateOpen(false)}>
          {createError && <div className="note is-error"><AlertCircle size={16} /><span>{createError}</span></div>}
          <form onSubmit={submitCreate} className="form">
            <label htmlFor="workspace-name">Tên không gian</label>
            <input id="workspace-name" data-autofocus type="text" value={newWs.name} onChange={e => setNewWs(v => ({ ...v, name: e.target.value }))} placeholder="ví dụ: Quy chế đào tạo, Nội quy công ty" required />
            <label htmlFor="workspace-description">Mô tả ngắn <small>(không bắt buộc)</small></label>
            <textarea id="workspace-description" value={newWs.desc} onChange={e => setNewWs(v => ({ ...v, desc: e.target.value }))} placeholder="Phạm vi, nội dung chính của bộ tài liệu…" rows={3} />
            <label htmlFor="workspace-pack">Lĩnh vực <small>(trợ lý chia việc cho chuyên gia của ngành này)</small></label>
            <select id="workspace-pack" value={newWs.pack} onChange={e => setNewWs(v => ({ ...v, pack: e.target.value as DomainPack }))}>
              {DOMAIN_PACKS.map(p => <option key={p.id} value={p.id}>{p.label}: {p.hint}</option>)}
            </select>
            <div className="dlg-actions">
              <button type="button" onClick={() => setCreateOpen(false)} className="btn btn-ghost">Hủy</button>
              <button type="submit" disabled={creating} className="btn btn-dark">{creating ? 'Đang tạo…' : 'Tạo không gian'}</button>
            </div>
          </form>
        </StudioModal>
      )}
    </>
  );
};
