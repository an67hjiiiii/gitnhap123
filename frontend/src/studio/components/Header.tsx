import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { LogOut, LogIn, X, AlertCircle, UserCheck, ChevronsUpDown, UserPlus, Plus, Check, MessagesSquare, FlaskConical, Database, Trash2 } from 'lucide-react';
import { HealthResponse, ExecutionMode, NavigationTab, User, Workspace } from '../types';
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
}

export const MODES: Record<ExecutionMode, { key: string; title: string; badge: string; desc: string }> = {
  proposed_adaptive: { key: 'C', title: 'Điều phối đầy đủ', badge: 'Đề xuất', desc: 'Điều kiện C: lập kế hoạch có kiểm tra, chuẩn hóa nhiệm vụ, tối ưu ngữ cảnh.' },
  naive_multi_agent: { key: 'B', title: 'Multi-Agent cơ bản', badge: 'Đối chứng', desc: 'Điều kiện B: có chia việc nhưng chưa tối ưu ngữ cảnh.' },
  vanilla_rag: { key: 'A', title: 'Vanilla RAG', badge: 'Đối chứng', desc: 'Điều kiện A: một lượt truy xuất, một lần sinh, không chia việc.' },
  ablation_comparison: { key: '⇄', title: 'So sánh ba phương pháp', badge: 'Thực nghiệm', desc: 'Chạy lần lượt A, B, C trên cùng một yêu cầu.' },
};

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
  onCreateWorkspace, onDeleteWorkspace, onLogout, isMobileDrawerOpen = false, onToggleMobileDrawer, children,
}) => {
  const [menu, setMenu] = useState<'ws' | 'profile' | null>(null);
  const [wsToDelete, setWsToDelete] = useState<Workspace | null>(null);
  const [deleteDocs, setDeleteDocs] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const closeMenu = React.useCallback(() => setMenu(null), []);
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

  const nav: { id: NavigationTab; label: string; Icon: typeof MessagesSquare; show: boolean }[] = [
    { id: 'orchestration', label: 'Không gian làm việc', Icon: MessagesSquare, show: true },
    { id: 'benchmarks', label: 'Thực nghiệm', Icon: FlaskConical, show: true },
    { id: 'db_explorer', label: 'Cơ sở dữ liệu', Icon: Database, show: user?.role === 'admin' },
  ];
  const go = (id: NavigationTab) => { onTabChange(id); if (isMobileDrawerOpen) onToggleMobileDrawer?.(); };

  return (
    <>
      {isMobileDrawerOpen && <div className="sb-overlay" onClick={onToggleMobileDrawer} />}
      <aside className={`sb${isMobileDrawerOpen ? ' is-open' : ''}`} aria-label="Thanh điều hướng">
        <div className="sb-brand">
          <Link to="/" title="Về trang giới thiệu đề tài" aria-label="OrchestrIQ Studio — về trang giới thiệu"><BrandLogo size="sm" showSubtitle={false} /></Link>
          {onToggleMobileDrawer && <button className="sb-x" onClick={onToggleMobileDrawer} aria-label="Đóng thanh bên"><X size={18} /></button>}
        </div>

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

        <nav className="sb-nav" aria-label="Chức năng chính">
          {nav.filter(n => n.show).map(({ id, label, Icon }) => (
            <button key={id} onClick={() => go(id)} aria-label={label} aria-current={activeTab === id ? 'page' : undefined} className={`sb-link${activeTab === id ? ' is-on' : ''}`}>
              <Icon size={17} /><span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sb-section">{children}</div>

        <div className="sb-foot">
          <p className="sb-status" title={ollamaOk ? 'Ollama đã kết nối' : 'Chưa kết nối Ollama'}>
            <i className={ollamaOk ? 'is-ok' : 'is-warn'} />{health?.ollama_model || 'qwen3:4b'} · {health?.database_type || 'PostgreSQL'}
            {!ollamaOk && <AlertCircle size={13} />}
          </p>
          {user ? (
            <div className="sb-pop" ref={profileRef}>
              <button className="sb-user" onClick={() => setMenu(menu === 'profile' ? null : 'profile')} aria-expanded={menu === 'profile'} aria-haspopup="menu">
                <span className="sb-avatar">{user.full_name.charAt(0)}</span>
                <span className="sb-user-text"><b>{user.full_name}</b><small>{ROLE_LABEL[user.role] ?? user.role}</small></span>
                <ChevronsUpDown size={15} />
              </button>
              {menu === 'profile' && (
                <div className="pop is-up" role="menu">
                  <p className="pop-label">@{user.username}</p>
                  <Link to="/login" role="menuitem" className="pop-item" onClick={() => setMenu(null)}><UserCheck size={15} />Đổi tài khoản</Link>
                  <Link to="/register" role="menuitem" className="pop-item" onClick={() => setMenu(null)}><UserPlus size={15} />Đăng ký hồ sơ mới</Link>
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
