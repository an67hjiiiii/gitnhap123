import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { SpellCheck, Users, LogOut, LogIn, X, AlertCircle, UserCheck, ChevronsUpDown, UserPlus, Plus, Check, MessagesSquare, FlaskConical, Database, Trash2, ClipboardCheck, GitCompareArrows, FileSearch, BarChart3, EyeOff, Search, Sun, Moon, Sparkles } from 'lucide-react';
import { HealthResponse, ExecutionMode, NavigationTab, User, Workspace } from '../types';
import { ActivityRow, getActivity, getNotifications, markNotificationsRead, answerInvite, myInvites, OrgNotification, OrgTerms, orgTerms, DOMAIN_PACKS, DomainPack, packLabel } from '../services/api';
import { Archive, Building2, ClipboardList, Library, Settings2, Wrench } from 'lucide-react';
import { RESEARCH_EVENT, researchMode } from '../utils/researchMode';
import '../styles/org.css';
import { Activity, Bell, Network, Palette, PanelLeftClose, PanelLeftOpen, Save, Upload } from 'lucide-react';
import '../styles/studio-shell.css';
import { PortalSwitch } from './admin/AdminPortal';
import { BrandLogo } from './BrandLogo';
import { StudioModal } from './StudioModal';
import { Avatar, AvatarDialog } from './Avatar';
import { NAV_ICONS } from './NavIcons';
import { ChevronLeft, ChevronRight, FileText, ImageUp } from 'lucide-react';

// bỏ dấu, chữ thường: tìm "bao mat" vẫn ra "Bảo mật"
const fold = (v: string) => v.normalize('NFD').replace(/\p{M}/gu, '').replace(/đ/gi, 'd').toLowerCase();
// ô của không gian: cá nhân dùng 6 kiểu cùng họ xanh lam (màu đậm nhạt + hoa văn khác nhau), gán theo thứ tự tạo;
// tổ chức dùng tím chàm. Hai chữ cái đầu giúp phân biệt thêm.
const WsTile: React.FC<{ ws: Workspace; className?: string; variant?: number }> = ({ ws, className = 'wsp-tile', variant = 0 }) => {
  const words = ws.name.trim().split(/\s+/).filter(w => /^\p{L}|^\d/u.test(w));
  const text = ((words[0]?.[0] ?? '?') + (words[1]?.[0] ?? '')).toUpperCase();
  return <span className={`${className} wsp-hue${ws.kind === 'org' ? ' is-org' : ''}`} data-v={ws.kind === 'org' ? undefined : variant % 6} aria-hidden="true">
    {ws.kind === 'org' ? <Building2 size={15} strokeWidth={2.2} /> : text}</span>;
};

interface HeaderProps {
  health: HealthResponse | null;
  mode?: ExecutionMode;
  onModeChange?: (m: ExecutionMode) => void;
  onSeedDocs: () => void;
  isSeeding: boolean;
  activeTab: NavigationTab;
  onTabChange: (tab: NavigationTab) => void;
  onOpenPalette?: () => void;
  theme?: 'light' | 'dark';
  onThemeChange?: (t: 'light' | 'dark', at?: { x: number; y: number }) => void;
  user: User | null;
  workspaces: Workspace[];
  currentWorkspaceId: number | string;
  onWorkspaceChange: (wsId: number | string) => void;
  onDeleteWorkspace?: (wsId: number | string, deleteSources: boolean) => Promise<void>;
  onCreateWorkspace?: (name: string, description: string, pack: DomainPack) => Promise<void>;
  /** đổi lĩnh vực của không gian đang mở (tổ chức: máy chủ kiểm quyền) */
  onChangeDomainPack?: (pack: DomainPack) => Promise<void>;
  onLogout: () => void;
  onUserChange?: (u: User) => void;
  isMobileDrawerOpen?: boolean;
  onToggleMobileDrawer?: () => void;
  children?: React.ReactNode;
  onOpenAdmin?: () => void;
  /** gọi lại sau khi nhận lời mời từ chuông thông báo (làm mới danh sách không gian) */
  onOrgChanged?: () => void;
}

export const MODES: Record<ExecutionMode, { key: string; title: string; badge: string; desc: string }> = {
  proposed_adaptive: { key: 'C', title: 'Điều phối đầy đủ', badge: 'Đề xuất', desc: 'Điều kiện C: lập kế hoạch có kiểm tra, chuẩn hóa nhiệm vụ, tối ưu ngữ cảnh.' },
  naive_multi_agent: { key: 'B', title: 'Multi-Agent cơ bản', badge: 'Đối chứng', desc: 'Điều kiện B: có chia việc nhưng chưa tối ưu ngữ cảnh.' },
  vanilla_rag: { key: 'A', title: 'Vanilla RAG', badge: 'Đối chứng', desc: 'Điều kiện A: một lượt truy xuất, một lần sinh, không chia việc.' },
  ablation_comparison: { key: '⇄', title: 'So sánh ba phương pháp', badge: 'Thực nghiệm', desc: 'Chạy lần lượt A, B, C trên cùng một yêu cầu.' },
};

function noteIcon(action: string) {
  const a = action.toLowerCase();
  if (/xóa/.test(a)) return Trash2;
  if (/nạp|tải lên/.test(a)) return Upload;
  if (/hỏi|trò chuyện/.test(a)) return MessagesSquare;
  if (/sơ đồ/.test(a)) return Network;
  if (/soát|chất lượng/.test(a)) return SpellCheck;
  if (/báo cáo|lưu/.test(a)) return Save;
  if (/tài khoản|mật khẩu|vai trò|phiên|đăng nhập/.test(a)) return UserCheck;
  if (/thiết kế|rà soát|mâu thuẫn|đánh giá|so sánh|truy vết|hồ sơ/.test(a)) return Sparkles;
  return Activity;
}
// t: tên gọi của không gian gửi thông báo nếu mình còn thuộc không gian đó, không thì dùng tên gọi doanh nghiệp
export function orgNoteText(n: OrgNotification, t: OrgTerms): string {
  const p = n.payload || {};
  const lv = (l?: string) => (l && (t.level as Record<string, string>)[l]) || '';
  const level = (q: Record<string, any>) => `${(t.cls as Record<string, string>)[q.classification] ?? q.classification}${q.department && !t.single ? ` · ${q.department}` : ''}`;
  switch (n.kind) {
    case 'invite': return `${p.inviter} mời bạn vào ${p.space_name} (${lv(p.level)})`;
    case 'join_request': return `${p.user} xin vào ${p.space_name}, chờ bạn duyệt`;
    case 'join_approved': return `Bạn đã được duyệt vào ${p.space_name} (${lv(p.level)})`;
    case 'join_rejected': return `Yêu cầu vào ${p.space_name} không được duyệt`;
    case 'invite_accepted': return `${p.user} đã tham gia ${p.space_name}`;
    case 'invite_declined': return `${p.user} đã từ chối lời mời vào ${p.space_name}`;
    case 'member_updated': return `Cấp bậc của bạn ở ${p.space_name}: ${lv(p.level)}${p.is_owner ? ' · Chủ' : ''}`;
    case 'member_removed': return `Bạn đã được gỡ khỏi ${p.space_name}`;
    case 'space_deleted': return `${p.by} đã xóa tổ chức ${p.space_name}`;
    case 'source_shared': return `${p.by} chia sẻ "${p.source_name}" với bạn (${p.space_name})`;
    case 'drafts_handed_over': return `Bạn nhận bàn giao ${p.count} bản nháp của ${p.from} (${p.space_name})`;
    case 'source_published': return `${p.by} tải lên "${p.source_name}" (${level(p)}) trong ${p.space_name}`;
    case 'doc_watch': {
      const found = [p.replaces?.length ? `thay thế ${p.replaces.join(', ')}` : '', p.replaced_by ? `đã bị thay thế (${p.replaced_by})` : '',
        p.conflicts ? `${p.conflicts} cặp câu có thể mâu thuẫn với tài liệu cũ, mở Kiểm tra mâu thuẫn để xác nhận` : ''].filter(Boolean);
      return `Tài liệu mới "${p.source_name}": ${found.join('; ')}`;
    }
    case 'request_submitted': return `${p.user} gửi đơn "${p.title}" chờ bạn duyệt (${p.space_name})`;
    case 'request_decided': return `Đơn "${p.title}" đã được ${p.decision === 'APPROVED' ? 'duyệt' : 'từ chối'} bởi ${p.by} (${p.space_name})`;
    case 'source_access_granted': return `Bạn giờ xem được "${p.source_name}": ${p.by} đổi sang ${level(p)}`;
    default: return 'Thông báo từ tổ chức';
  }
}
function ago(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').getTime()) / 1000);
  if (s < 60) return 'vừa xong';
  if (s < 3600) return `${Math.floor(s / 60)} phút`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ`;
  return `${Math.floor(s / 86400)} ngày`;
}

const ROLE_LABEL: Record<string, string> = { tech_lead: 'Trưởng nhóm', researcher: 'Nghiên cứu', developer: 'Người dùng', admin: 'Quản trị' };

// Đóng menu khi bấm ra ngoài hoặc nhấn Esc.
export function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    document.addEventListener('mousedown', onDown); document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open, close]);
  return ref;
}

// Thanh bên: không gian làm việc, điều hướng, kho tri thức (children) và tài khoản.
export const Header: React.FC<HeaderProps> = ({
  health, activeTab, onTabChange, user, workspaces, currentWorkspaceId, onWorkspaceChange,
  onCreateWorkspace, onChangeDomainPack, onDeleteWorkspace, onLogout, onUserChange, isMobileDrawerOpen = false, onToggleMobileDrawer, onOpenPalette, theme = 'light', onThemeChange, children, onOpenAdmin, onOrgChanged,
}) => {
  const [menu, setMenu] = useState<'ws' | 'profile' | 'notif' | null>(null);
  const uid = user?.email || user?.username;
  const [research, setResearch] = useState(researchMode(uid));
  useEffect(() => setResearch(researchMode(uid)), [uid]);
  useEffect(() => {
    const open = () => setAvatarOpen(true);  // trang Cài đặt mở hộp đổi ảnh đại diện
    window.addEventListener('oq-open-avatar', open);
    return () => window.removeEventListener('oq-open-avatar', open);
  }, []);
  useEffect(() => {
    const on = (e: Event) => setResearch(!!(e as CustomEvent).detail);
    window.addEventListener(RESEARCH_EVENT, on);
    return () => window.removeEventListener(RESEARCH_EVENT, on);
  }, []);
  const [avatarOpen, setAvatarOpen] = useState(false);
  const [wsQuery, setWsQuery] = useState('');
  // kiểu ô theo thứ tự tạo: không gian tạo sau nhận kiểu kế tiếp
  const wsVariant = React.useMemo(() => new Map(workspaces.filter(w => w.kind !== 'org')
    .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)) || String(a.id).localeCompare(String(b.id)))
    .map((w, i) => [w.id, i])), [workspaces]);
  useEffect(() => { if (menu !== 'ws') setWsQuery(''); }, [menu]);
  // Phóng đại quanh con trỏ, giữ nguyên tâm từng ô để thanh bên không lệch trục.
  const magFrame = useRef(0);
  const magnify = (e: React.MouseEvent<HTMLElement>) => {
    if (!rail || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    cancelAnimationFrame(magFrame.current);
    const nav = e.currentTarget, y = e.clientY;
    magFrame.current = requestAnimationFrame(() => {
      const icons = [...nav.querySelectorAll<HTMLElement>('.sb-ico')];
      const centers = icons.map(icon => { const r = icon.parentElement!.getBoundingClientRect(); return r.top + r.height / 2; });
      icons.forEach((icon, i) => {
        const distance = Math.min(1, Math.abs(centers[i] - y) / 100);
        const scale = 1 + .65 * (1 + Math.cos(Math.PI * distance)) / 2;
        icon.style.setProperty('--mag', scale.toFixed(3));
      });
      magFrame.current = 0;
    });
  };
  const unmagnify = (e: React.MouseEvent<HTMLElement>) => {
    cancelAnimationFrame(magFrame.current);
    e.currentTarget.querySelectorAll<HTMLElement>('.sb-ico').forEach(icon => icon.style.removeProperty('--mag'));
  };
  useEffect(() => () => cancelAnimationFrame(magFrame.current), []);
  // chú thích nổi khi thanh bên thu gọn (nằm ngoài vùng cuộn nên không bị cắt)
  // cập nhật thẳng phần tử chú thích, không qua state, để rê chuột không làm vẽ lại cả thanh bên
  const tipRef = useRef<HTMLSpanElement>(null);
  const showTip = (e: React.SyntheticEvent<HTMLElement>) => {
    const sb = e.currentTarget.closest('.sb'), tip = tipRef.current;
    if (!tip || !sb?.classList.contains('is-rail')) return;
    const r = e.currentTarget.getBoundingClientRect();
    tip.textContent = e.currentTarget.getAttribute('aria-label') ?? '';
    tip.style.top = `${r.top + r.height / 2 - sb.getBoundingClientRect().top}px`;
    tip.hidden = false;
  };
  const hideTip = () => { if (tipRef.current) tipRef.current.hidden = true; };
  // Thu gọn thanh bên thành dải biểu tượng (chỉ màn rộng); nhớ lựa chọn; Ctrl+B để bật/tắt.
  const [rail, setRail] = useState(() => { try { return localStorage.getItem('orchestriq-sb-rail') === '1'; } catch { return false; } });
  const toggleRail = () => setRail(v => { const n = !v; try { localStorage.setItem('orchestriq-sb-rail', n ? '1' : '0'); } catch { /* chế độ riêng tư */ } return n; });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b' && !e.shiftKey && !e.altKey) { e.preventDefault(); toggleRail(); } };
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey);
  }, []);
  // Thông báo: các hoạt động gần đây thật của tài khoản (nhật ký hệ thống); số chưa xem tính theo lần mở gần nhất.
  const [notes, setNotes] = useState<ActivityRow[]>([]);
  const [seenAt, setSeenAt] = useState(() => { try { return localStorage.getItem('orchestriq-notif-seen') || ''; } catch { return ''; } });
  useEffect(() => {
    if (!user) return;
    let alive = true;
    const load = () => getActivity(8).then(r => alive && setNotes(r)).catch(() => undefined);
    load(); const t = window.setInterval(() => { if (!document.hidden) load(); }, 60000);
    return () => { alive = false; window.clearInterval(t); };
  }, [user?.username]);
  const [orgNotes, setOrgNotes] = useState<OrgNotification[]>([]);
  const [orgUnread, setOrgUnread] = useState(0);
  // lời mời còn hiệu lực: chỉ những lời mời này mới hiện nút Tham gia / Từ chối (lời mời đã trả lời thì chỉ còn dòng chữ)
  const [openInvites, setOpenInvites] = useState<Set<string>>(new Set());
  const loadOrg = () => Promise.all([getNotifications(), myInvites().catch(() => [])]).then(([r, inv]) => {
    setOrgNotes(r.items.slice(0, 8)); setOrgUnread(r.unread); setOpenInvites(new Set(inv.map(i => i.invite_id)));
  }).catch(() => undefined);
  useEffect(() => {
    if (!user) return;
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
  const [wsToDelete, setWsToDelete] = useState<Workspace | null>(null);
  const [deleteDocs, setDeleteDocs] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const closeMenu = React.useCallback(() => setMenu(null), []);
  const notifRef = useDismiss(menu === 'notif', closeMenu);
  const wsRef = useDismiss(menu === 'ws', closeMenu);
  const profileRef = useDismiss(menu === 'profile', closeMenu);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newWsName, setNewWsName] = useState('');
  const [newWsDesc, setNewWsDesc] = useState('');
  const [newWsPack, setNewWsPack] = useState<DomainPack>('general');
  const [packBusy, setPackBusy] = useState(false);
  const [packError, setPackError] = useState<string | null>(null);
  const [isCreatingWs, setIsCreatingWs] = useState(false);
  const [createWsError, setCreateWsError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!isCreateModalOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    dialogRef.current?.querySelector<HTMLInputElement>('input')?.focus();
    return () => previous?.focus();
  }, [isCreateModalOpen]);

  const currentWorkspace = workspaces.find(w => w.id === currentWorkspaceId) || workspaces[0];
  const ollamaOk = !!health?.ollama_status?.includes('CONNECTED');

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWsName.trim()) { setCreateWsError('Vui lòng nhập tên không gian làm việc.'); return; }
    if (!onCreateWorkspace) return;
    setIsCreatingWs(true); setCreateWsError(null);
    try {
      await onCreateWorkspace(newWsName.trim(), newWsDesc.trim(), newWsPack);
      setNewWsName(''); setNewWsDesc(''); setNewWsPack('general'); setIsCreateModalOpen(false); setMenu(null);
    } catch (err: any) {
      setCreateWsError(err.message || 'Không thể tạo không gian làm việc mới.');
    } finally {
      setIsCreatingWs(false);
    }
  };

  // viên trượt đi theo mục đang mở trên thanh bên
  const navRef = useRef<HTMLElement>(null);
  const glideRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const place = () => {
      const g = glideRef.current, on = navRef.current?.querySelector<HTMLElement>('.sb-link.is-on');
      if (!g) return;
      if (!on) { g.style.opacity = '0'; return; }
      g.style.opacity = '1'; g.style.height = `${on.offsetHeight}px`; g.style.transform = `translateY(${on.offsetTop}px)`;
    };
    place();
    window.addEventListener('resize', place);
    const t = window.setTimeout(place, 320);
    return () => { window.clearTimeout(t); window.removeEventListener('resize', place); };
  }, [activeTab, user?.role, rail]);

  // Đợt 6 (mục 2b): bố cục 7 trang. Việc cần làm chỉ khi đang mở tổ chức; Nghiên cứu cho quản trị hoặc chế độ nhà nghiên cứu.
  const inOrg = currentWorkspace?.kind === 'org';
  const showResearch = user?.role === 'admin' || research;
  const nav: { id: NavigationTab; label: string; Icon: typeof MessagesSquare; show: boolean }[] = [
    { id: 'orchestration', label: 'Không gian làm việc', Icon: MessagesSquare, show: true },
    { id: 'library', label: 'Thư viện tài liệu', Icon: Library, show: true },
    { id: 'results', label: 'Kết quả đã lưu', Icon: Archive, show: true },
    { id: 'tasks', label: 'Việc cần làm', Icon: ClipboardList, show: !!user && inOrg },
    { id: 'organization', label: 'Tổ chức', Icon: Building2, show: !!user },
    { id: 'overview', label: 'Tổng quan', Icon: BarChart3, show: true },
    { id: 'settings', label: 'Cài đặt', Icon: Settings2, show: !!user },
    { id: 'evaluation', label: 'Phòng đánh giá', Icon: ClipboardCheck, show: showResearch },
    { id: 'benchmarks', label: 'Thực nghiệm', Icon: FlaskConical, show: showResearch },
    { id: 'rating', label: 'Chấm mù', Icon: EyeOff, show: showResearch },
    { id: 'users', label: 'Người dùng', Icon: Users, show: user?.role === 'admin' },
    { id: 'db_explorer', label: 'Cơ sở dữ liệu', Icon: Database, show: user?.role === 'admin' },
  ];
  const go = (id: NavigationTab) => { onTabChange(id); if (isMobileDrawerOpen) onToggleMobileDrawer?.(); };

  return (
    <>
      {isMobileDrawerOpen && <div className="sb-overlay" onClick={onToggleMobileDrawer} />}
      <aside className={`sb${isMobileDrawerOpen ? ' is-open' : ''}${rail && !isMobileDrawerOpen ? ' is-rail' : ''}`} aria-label="Thanh điều hướng">
        <div className="sb-brand">
          <Link to="/" className="sb-logo" title="Về trang giới thiệu đề tài" aria-label="OrchestrIQ Studio, về trang giới thiệu"><BrandLogo size="sm" showSubtitle={false} /></Link>
          {onToggleMobileDrawer && <button className="sb-x" onClick={onToggleMobileDrawer} aria-label="Đóng thanh bên"><X size={18} /></button>}
          <div className="sb-tools">
            {user && <div className="sb-pop" ref={notifRef}>
              <button type="button" className="sb-icon" onClick={openNotif} aria-expanded={menu === 'notif'} aria-haspopup="dialog" aria-label={unread ? `Thông báo, ${unread} mục mới` : 'Thông báo'} title="Thông báo">
                <Bell size={17} />{unread > 0 && <i className="sb-badge">{unread > 9 ? '9+' : unread}</i>}
              </button>
              {menu === 'notif' && <div className="pop sb-notif" role="dialog" aria-label="Hoạt động gần đây">
                {orgNotes.length > 0 && <><div className="sb-notif-head"><b>Tổ chức</b><button type="button" className="dp-link" onClick={() => { setMenu(null); go('organization'); }}>Mở trang Tổ chức</button></div>
                <ul className="og-notes">{orgNotes.map(n => <li key={n.notification_id} className={n.read ? '' : 'is-unread'}>
                  <span className="sb-notif-ico"><Building2 size={15} /></span>
                  <span className="sb-notif-t"><b>{orgNoteText(n, orgTerms(workspaces.find(w => w.id === n.space_id)))}</b>
                    {n.kind === 'invite' && n.payload.invite_id && (answered[n.payload.invite_id] || !openInvites.has(n.payload.invite_id)
                      ? <small>{answered[n.payload.invite_id] ?? 'Đã xử lý'}</small>
                      : <span className="og-note-acts"><button type="button" className="btn btn-dark is-sm" onClick={() => answer(n.payload.invite_id, 'accept')}>Tham gia</button>
                        <button type="button" className="btn btn-ghost is-sm" onClick={() => answer(n.payload.invite_id, 'decline')}>Từ chối</button></span>)}</span>
                  <time>{ago(n.created_at)}</time></li>)}</ul></>}
                <div className="sb-notif-head"><b>Hoạt động gần đây</b><button type="button" className="dp-link" onClick={() => { setMenu(null); go('overview'); }}>Xem tất cả</button></div>
                {notes.length === 0 ? <p className="sb-notif-empty">Chưa có hoạt động nào.</p> : <ul>{notes.map((n, i) => {
                  const I = noteIcon(n.action);
                  return <li key={i} className={n.status >= 400 ? 'is-bad' : ''}><span className="sb-notif-ico"><I size={15} /></span>
                    <span className="sb-notif-t"><b>{n.action}</b>{n.target && !/^(usr|sp|src|inv|shr|dep|rs|rpt|ws)_[A-Za-z0-9_-]+$/.test(n.target) && <small>{n.target}</small>}</span><time>{ago(n.created_at)}</time></li>;
                })}</ul>}
              </div>}
            </div>}
            <button type="button" className="sb-icon sb-rail-btn" onClick={toggleRail} aria-pressed={rail} aria-label={rail ? 'Mở rộng thanh bên (Ctrl+B)' : 'Thu gọn thanh bên (Ctrl+B)'} title={rail ? 'Mở rộng (Ctrl+B)' : 'Thu gọn (Ctrl+B)'}>
              {rail ? <ChevronRight size={15} strokeWidth={2.4} /> : <ChevronLeft size={15} strokeWidth={2.4} />}
            </button>
          </div>
        </div>

        {onOpenAdmin && <PortalSwitch portal="research" onChange={p => p === 'admin' && onOpenAdmin()} />}
        <div className="sb-pop" ref={wsRef}>
          {workspaces.length <= 1 && !onCreateWorkspace ? (
            // CAP1: mỗi người một kho tài liệu, không có gì để chuyển nên hiển thị nhãn tĩnh.
            <div className="sb-ws is-static" title="Kho tài liệu riêng của tài khoản">
              <span className="sb-ws-mark">{(currentWorkspace?.name || '?').charAt(0).toUpperCase()}</span>
              <span className="sb-ws-name">{currentWorkspace?.name || 'Kho tài liệu'}</span>
            </div>
          ) : (
          <button className="sb-ws" onClick={() => setMenu(menu === 'ws' ? null : 'ws')} aria-expanded={menu === 'ws'} aria-haspopup="menu" title="Chuyển không gian làm việc">
            {currentWorkspace ? <WsTile ws={currentWorkspace} className="sb-ws-mark" variant={wsVariant.get(currentWorkspace.id)} /> : <span className="sb-ws-mark">?</span>}
            <span className="sb-ws-name">{currentWorkspace?.name || 'Chưa chọn không gian'}</span>
            <ChevronsUpDown size={15} />
          </button>
          )}
          {menu === 'ws' && (() => {
            const q = fold(wsQuery.trim());
            const shown = q ? workspaces.filter(w => fold(w.name).includes(q)) : workspaces;
            const canDelete = !!onDeleteWorkspace && workspaces.filter(w => w.kind !== 'org').length > 1;
            const groups = [['Cá nhân', shown.filter(w => w.kind !== 'org')], ['Tổ chức', shown.filter(w => w.kind === 'org')]] as const;
            return (
              <div className="pop wsp-pop" role="menu" aria-label="Không gian làm việc">
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
                {/* đợt 6: bỏ chọn lĩnh vực cho cả không gian; tác tử theo loại việc tự chọn, bộ công cụ chọn ngành bên trong */}
                {onCreateWorkspace && <button className="wsp-new" onClick={() => { setMenu(null); setIsCreateModalOpen(true); }}>
                  <span className="wsp-new-ico"><Plus size={16} strokeWidth={2.4} /></span><span className="wsp-info"><b>Tạo không gian mới</b><small>Kho tài liệu và lịch sử trò chuyện riêng</small></span></button>}
              </div>
            );
          })()}
        </div>

        <div className="sb-scroll">
          {onOpenPalette && <button type="button" className="sb-search" onClick={onOpenPalette} title={rail ? "Tìm nhanh (Ctrl K)" : undefined}><Search size={15} /><span>Tìm nhanh</span><kbd>Ctrl K</kbd></button>}
          <nav className="sb-nav" aria-label="Chức năng chính" ref={navRef} onMouseMove={magnify} onMouseLeave={unmagnify}>
            <span className="sb-glide" ref={glideRef} aria-hidden="true" />
            {nav.filter(n => n.show).map(({ id, label, Icon }) => (
              <React.Fragment key={id}>
                {id === 'evaluation' && <p className="sb-group">Nghiên cứu</p>}
                {id === 'users' && <p className="sb-group">Quản trị</p>}
                <button onClick={() => go(id)} aria-label={label} aria-current={activeTab === id ? 'page' : undefined} className={`sb-link${activeTab === id ? ' is-on' : ''}`}
                  onMouseEnter={showTip} onFocus={showTip} onMouseLeave={hideTip} onBlur={hideTip}>
                  <span className="sb-ico" data-tone={id}>{NAV_ICONS[id] ?? <Icon size={16} strokeWidth={2.2} />}</span><span>{label}</span>
                </button>
              </React.Fragment>
            ))}
          </nav>

          <div className="sb-section">{children}</div>
        </div>
        {rail && <span className="sb-tip" ref={tipRef} hidden aria-hidden="true" />}

        <div className="sb-foot">
          <div className="sb-foot-row">
            {/* tên mô hình / CSDL xem ở trang Tổng quan; thanh bên chỉ báo khi có việc cần làm (mô hình chưa chạy) */}
            {!ollamaOk && <p className="sb-status" role="status" title="Chạy Ollama (MO_ORCHESTRIQ.cmd hoặc Ctrl+Shift+B) để hỏi đáp và phân tích">
              <i className="is-warn" />Chưa kết nối mô hình<AlertCircle size={13} />
            </p>}

          </div>
          {user ? (
            <div className="sb-pop" ref={profileRef}>
              <button className="sb-user" onClick={() => setMenu(menu === 'profile' ? null : 'profile')} aria-expanded={menu === 'profile'} aria-haspopup="menu">
                <Avatar value={user.avatar} className="sb-avatar">{user.full_name.charAt(0)}</Avatar>
                <span className="sb-user-text"><b>{user.full_name}</b><small>{ROLE_LABEL[user.role] ?? user.role}</small></span>
                <ChevronsUpDown size={15} />
              </button>
              {onThemeChange && <button type="button" className="sb-icon sb-theme" aria-label={theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'} title={theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'}
                onClick={e => onThemeChange(theme === 'dark' ? 'light' : 'dark', { x: e.clientX, y: e.clientY })}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}</button>}
              {menu === 'profile' && (
                <div className="pop is-up" role="menu">
                  <div className="sb-me"><Avatar value={user.avatar} className="sb-avatar is-lg">{user.full_name.charAt(0)}</Avatar><span><b>{user.full_name}</b><small>{user.username}</small></span></div>
                  <p className="pop-label">Cài đặt</p>
                  {onThemeChange && <div className="sb-set"><span><Palette size={15} />Giao diện</span>
                    <span className="sb-seg" role="group" aria-label="Chọn giao diện">
                      <button type="button" aria-pressed={theme === 'light'} onClick={e => onThemeChange('light', { x: e.clientX, y: e.clientY })}><Sun size={13} />Sáng</button>
                      <button type="button" aria-pressed={theme === 'dark'} onClick={e => onThemeChange('dark', { x: e.clientX, y: e.clientY })}><Moon size={13} />Tối</button>
                    </span></div>}
                  {onUserChange && <button role="menuitem" className="pop-item" onClick={() => { setMenu(null); setAvatarOpen(true); }}><ImageUp size={15} />Đổi ảnh đại diện</button>}
                  <button role="menuitem" className="pop-item" onClick={() => { toggleRail(); setMenu(null); }}>{rail ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}{rail ? 'Mở rộng thanh bên' : 'Thu gọn thanh bên'}<kbd>Ctrl B</kbd></button>
                  {onOpenPalette && <button role="menuitem" className="pop-item" onClick={() => { setMenu(null); onOpenPalette(); }}><Search size={15} />Tìm nhanh và chuyển trang<kbd>Ctrl K</kbd></button>}
                  <div className="pop-sep" />
                  <Link to="/login" role="menuitem" className="pop-item" onClick={() => setMenu(null)}><UserCheck size={15} />Đổi tài khoản</Link>
                  <button role="menuitem" className="pop-item is-danger" onClick={() => { setMenu(null); onLogout(); }}><LogOut size={15} />Đăng xuất</button>
                </div>
              )}
            </div>
          ) : (
            <Link to="/login" className="btn btn-dark btn-block"><LogIn size={15} />Đăng nhập</Link>
          )}
        </div>
      </aside>

      {avatarOpen && user && onUserChange && <AvatarDialog user={user} onClose={() => setAvatarOpen(false)} onSaved={onUserChange} />}

      {wsToDelete && onDeleteWorkspace && (
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

      {isCreateModalOpen && (
        <div className="dlg-backdrop">
          <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="workspace-dialog-title" className="dlg" onKeyDown={e => {
            if (e.key === 'Escape') setIsCreateModalOpen(false);
            if (e.key === 'Tab') {
              const nodes = dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input, textarea');
              if (!nodes?.length) return;
              const first = nodes[0], last = nodes[nodes.length - 1];
              if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
              else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
            }
          }}>
            <div className="dlg-head">
              <div><h3 id="workspace-dialog-title">Tạo không gian làm việc</h3><p>Mỗi không gian có kho tài liệu và lịch sử lượt chạy riêng.</p></div>
              <button onClick={() => setIsCreateModalOpen(false)} aria-label="Đóng hộp thoại tạo không gian làm việc" className="icon-btn"><X size={16} /></button>
            </div>
            {createWsError && <div className="note is-error"><AlertCircle size={16} /><span>{createWsError}</span></div>}
            <form onSubmit={handleCreateSubmit} className="form">
              <label htmlFor="workspace-name">Tên không gian</label>
              <input id="workspace-name" type="text" value={newWsName} onChange={e => setNewWsName(e.target.value)} placeholder="ví dụ: Quy chế đào tạo, Nội quy công ty" required />
              <label htmlFor="workspace-description">Mô tả ngắn <small>(không bắt buộc)</small></label>
              <textarea id="workspace-description" value={newWsDesc} onChange={e => setNewWsDesc(e.target.value)} placeholder="Phạm vi, nội dung chính của bộ tài liệu…" rows={3} />
              <label htmlFor="workspace-pack">Lĩnh vực <small>(trợ lý chia việc cho chuyên gia của ngành này)</small></label>
              <select id="workspace-pack" value={newWsPack} onChange={e => setNewWsPack(e.target.value as DomainPack)}>
                {DOMAIN_PACKS.map(p => <option key={p.id} value={p.id}>{p.label}: {p.hint}</option>)}
              </select>
              <div className="dlg-actions">
                <button type="button" onClick={() => setIsCreateModalOpen(false)} className="btn btn-ghost">Hủy</button>
                <button type="submit" disabled={isCreatingWs} className="btn btn-dark">{isCreatingWs ? 'Đang tạo…' : 'Tạo không gian'}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
};
