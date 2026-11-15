import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { SpellCheck, Users, LogOut, LogIn, X, AlertCircle, UserCheck, ChevronsUpDown, UserPlus, Plus, Check, MessagesSquare, FlaskConical, Database, Trash2, ListChecks, PencilRuler, ShieldCheck, ClipboardCheck, GitCompareArrows, FileSearch, BarChart3, EyeOff, Search, Sun, Moon, Sparkles } from 'lucide-react';
import { HealthResponse, ExecutionMode, NavigationTab, User, Workspace } from '../types';
import { ActivityRow, getActivity } from '../services/api';
import { Activity, Bell, Network, Palette, PanelLeftClose, PanelLeftOpen, Save, Upload } from 'lucide-react';
import '../styles/studio-shell.css';
import { PortalSwitch } from './admin/AdminPortal';
import { BrandLogo } from './BrandLogo';
import { StudioModal } from './StudioModal';

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
  onCreateWorkspace?: (name: string, description: string) => Promise<void>;
  onLogout: () => void;
  isMobileDrawerOpen?: boolean;
  onToggleMobileDrawer?: () => void;
  children?: React.ReactNode;
  onOpenAdmin?: () => void;
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
function ago(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').getTime()) / 1000);
  if (s < 60) return 'vừa xong';
  if (s < 3600) return `${Math.floor(s / 60)} phút`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ`;
  return `${Math.floor(s / 86400)} ngày`;
}

const ROLE_LABEL: Record<string, string> = { tech_lead: 'Trưởng nhóm', researcher: 'Nghiên cứu', developer: 'Phát triển', admin: 'Quản trị' };

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
  onCreateWorkspace, onDeleteWorkspace, onLogout, isMobileDrawerOpen = false, onToggleMobileDrawer, onOpenPalette, theme = 'light', onThemeChange, children, onOpenAdmin,
}) => {
  const [menu, setMenu] = useState<'ws' | 'profile' | 'notif' | null>(null);
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
  const unread = notes.filter(n => !seenAt || n.created_at > seenAt).length;
  const openNotif = () => {
    const next = menu === 'notif' ? null : 'notif';
    setMenu(next);
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
      await onCreateWorkspace(newWsName.trim(), newWsDesc.trim());
      setNewWsName(''); setNewWsDesc(''); setIsCreateModalOpen(false); setMenu(null);
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

  const nav: { id: NavigationTab; label: string; Icon: typeof MessagesSquare; show: boolean }[] = [
    { id: 'orchestration', label: 'Không gian làm việc', Icon: MessagesSquare, show: true },
    { id: 'overview', label: 'Tổng quan', Icon: BarChart3, show: true },
    { id: 'documents', label: 'Hồ sơ tài liệu', Icon: FileSearch, show: true },
    { id: 'traceability', label: 'Truy vết yêu cầu', Icon: ListChecks, show: true },
    { id: 'req_quality', label: 'Chất lượng yêu cầu', Icon: SpellCheck, show: true },
    { id: 'design', label: 'Gói thiết kế', Icon: PencilRuler, show: true },
    { id: 'security', label: 'Rà soát bảo mật', Icon: ShieldCheck, show: true },
    { id: 'consistency', label: 'Kiểm tra mâu thuẫn', Icon: GitCompareArrows, show: true },
    { id: 'evaluation', label: 'Phòng đánh giá', Icon: ClipboardCheck, show: true },
    { id: 'benchmarks', label: 'Thực nghiệm', Icon: FlaskConical, show: true },
    { id: 'rating', label: 'Chấm mù', Icon: EyeOff, show: true },
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
                <div className="sb-notif-head"><b>Hoạt động gần đây</b><button type="button" className="dp-link" onClick={() => { setMenu(null); go('overview'); }}>Xem tất cả</button></div>
                {notes.length === 0 ? <p className="sb-notif-empty">Chưa có hoạt động nào.</p> : <ul>{notes.map((n, i) => {
                  const I = noteIcon(n.action);
                  return <li key={i} className={n.status >= 400 ? 'is-bad' : ''}><span className="sb-notif-ico"><I size={15} /></span>
                    <span className="sb-notif-t"><b>{n.action}</b>{n.target && <small>{n.target}</small>}</span><time>{ago(n.created_at)}</time></li>;
                })}</ul>}
              </div>}
            </div>}
            <button type="button" className="sb-icon sb-rail-btn" onClick={toggleRail} aria-pressed={rail} aria-label={rail ? 'Mở rộng thanh bên (Ctrl+B)' : 'Thu gọn thanh bên (Ctrl+B)'} title={rail ? 'Mở rộng (Ctrl+B)' : 'Thu gọn (Ctrl+B)'}>
              {rail ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
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
            <span className="sb-ws-mark">{(currentWorkspace?.name || '?').charAt(0).toUpperCase()}</span>
            <span className="sb-ws-name">{currentWorkspace?.name || 'Chưa chọn không gian'}</span>
            <ChevronsUpDown size={15} />
          </button>
          )}
          {menu === 'ws' && (
            <div className="pop" role="menu">
              <p className="pop-label">Không gian làm việc</p>
              <div className="pop-scroll">
                {workspaces.map(ws => (
                  <div key={ws.id} className="pop-row">
                    <button role="menuitem" className="pop-item" onClick={() => { onWorkspaceChange(ws.id); setMenu(null); }}>
                      <span className="sb-ws-mark is-sm">{ws.name.charAt(0).toUpperCase()}</span>
                      <span className="pop-text"><b>{ws.name}</b><small>{ws.documents_count} tài liệu · {ws.runs_count} cuộc trò chuyện</small></span>
                      {ws.id === currentWorkspaceId && <Check size={15} className="pop-check" />}
                    </button>
                    {onDeleteWorkspace && workspaces.length > 1 && (
                      <button className="pop-del" aria-label={`Xóa không gian ${ws.name}`} title="Xóa không gian"
                        onClick={() => { setMenu(null); setDeleteDocs(false); setWsToDelete(ws); }}><Trash2 size={14} /></button>
                    )}
                  </div>
                ))}
              </div>
              {onCreateWorkspace && <button className="pop-item is-add" onClick={() => { setMenu(null); setIsCreateModalOpen(true); }}><Plus size={15} />Tạo không gian mới</button>}
            </div>
          )}
        </div>

        <div className="sb-scroll">
          {onOpenPalette && <button type="button" className="sb-search" onClick={onOpenPalette} title={rail ? "Tìm nhanh (Ctrl K)" : undefined}><Search size={15} /><span>Tìm nhanh</span><kbd>Ctrl K</kbd></button>}
          <nav className="sb-nav" aria-label="Chức năng chính" ref={navRef}>
            <span className="sb-glide" ref={glideRef} aria-hidden="true" />
            {nav.filter(n => n.show).map(({ id, label, Icon }) => (
              <React.Fragment key={id}>
                {id === 'documents' && <p className="sb-group">Công cụ phân tích</p>}
                {id === 'benchmarks' && <p className="sb-group">Nghiên cứu</p>}
                {id === 'users' && <p className="sb-group">Quản trị</p>}
                <button onClick={() => go(id)} aria-label={label} aria-current={activeTab === id ? 'page' : undefined} className={`sb-link${activeTab === id ? ' is-on' : ''}`} title={rail ? label : undefined}>
                  <Icon size={16} /><span>{label}</span>
                </button>
              </React.Fragment>
            ))}
          </nav>

          <div className="sb-section">{children}</div>
        </div>

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
                <span className="sb-avatar">{user.full_name.charAt(0)}</span>
                <span className="sb-user-text"><b>{user.full_name}</b><small>{ROLE_LABEL[user.role] ?? user.role}</small></span>
                <ChevronsUpDown size={15} />
              </button>
              {onThemeChange && <button type="button" className="sb-icon sb-theme" aria-label={theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'} title={theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'}
                onClick={e => onThemeChange(theme === 'dark' ? 'light' : 'dark', { x: e.clientX, y: e.clientY })}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}</button>}
              {menu === 'profile' && (
                <div className="pop is-up" role="menu">
                  <div className="sb-me"><span className="sb-avatar is-lg">{user.full_name.charAt(0)}</span><span><b>{user.full_name}</b><small>{user.username}</small></span></div>
                  <p className="pop-label">Cài đặt</p>
                  {onThemeChange && <div className="sb-set"><span><Palette size={15} />Giao diện</span>
                    <span className="sb-seg" role="group" aria-label="Chọn giao diện">
                      <button type="button" aria-pressed={theme === 'light'} onClick={e => onThemeChange('light', { x: e.clientX, y: e.clientY })}><Sun size={13} />Sáng</button>
                      <button type="button" aria-pressed={theme === 'dark'} onClick={e => onThemeChange('dark', { x: e.clientX, y: e.clientY })}><Moon size={13} />Tối</button>
                    </span></div>}
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
              <label htmlFor="workspace-name">Tên dự án</label>
              <input id="workspace-name" type="text" value={newWsName} onChange={e => setNewWsName(e.target.value)} placeholder="ví dụ: Hệ thống thanh toán nội bộ" required />
              <label htmlFor="workspace-description">Mô tả ngắn <small>(không bắt buộc)</small></label>
              <textarea id="workspace-description" value={newWsDesc} onChange={e => setNewWsDesc(e.target.value)} placeholder="Phạm vi, ràng buộc kỹ thuật chính…" rows={3} />
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
