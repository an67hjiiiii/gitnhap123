import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { SpellCheck, Users, X, UserCheck, MessagesSquare, FlaskConical, Database, Trash2, ClipboardCheck, GitCompareArrows, BarChart3, EyeOff, Search, Sparkles, AlertCircle } from 'lucide-react';
import { HealthResponse, ExecutionMode, NavigationTab, User } from '../types';
import { OrgNotification, OrgTerms } from '../services/api';
import { Archive, Building2, Library, Wrench } from 'lucide-react';
import { RESEARCH_EVENT, researchMode } from '../utils/researchMode';
import '../styles/org.css';
import { Activity, Network, Save, Upload, Layers, Cpu } from 'lucide-react';
import '../styles/studio-shell.css';
import { PortalSwitch } from './admin/AdminPortal';
import { BrandLogo } from './BrandLogo';
import { Bot, ChevronLeft, ChevronRight, FileText, FolderOpen, Inbox } from 'lucide-react';

export const MODES: Record<ExecutionMode, { key: string; title: string; badge: string; desc: string }> = {
  proposed_adaptive: { key: 'C', title: 'Điều phối đầy đủ', badge: 'Đề xuất', desc: 'Điều kiện C: lập kế hoạch có kiểm tra, chuẩn hóa nhiệm vụ, tối ưu ngữ cảnh.' },
  naive_multi_agent: { key: 'B', title: 'Multi-Agent cơ bản', badge: 'Đối chứng', desc: 'Điều kiện B: có chia việc nhưng chưa tối ưu ngữ cảnh.' },
  vanilla_rag: { key: 'A', title: 'Vanilla RAG', badge: 'Đối chứng', desc: 'Điều kiện A: một lượt truy xuất, một lần sinh, không chia việc.' },
  ablation_comparison: { key: '⇄', title: 'So sánh ba phương pháp', badge: 'Thực nghiệm', desc: 'Chạy lần lượt A, B, C trên cùng một yêu cầu.' },
};

export function noteIcon(action: string) {
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

interface SidebarProps {
  health: HealthResponse | null;
  activeTab: NavigationTab;
  onTabChange: (tab: NavigationTab) => void;
  onOpenPalette?: () => void;
  user: User | null;
  isMobileDrawerOpen?: boolean;
  onToggleMobileDrawer?: () => void;
  onOpenAdmin?: () => void;
  docCount: number;
  chunkCount: number;
  /** chọn không gian (đầu thanh bên) và tài khoản, lịch sử, thông báo, trợ giúp (chân thanh bên) — thay thanh trên cùng */
  top?: React.ReactNode;
  bottom?: React.ReactNode;
}

// trang con được tô theo mục cha: Hồ sơ tài liệu, Kiểm tra mâu thuẫn, So sánh phiên bản thuộc Tài liệu;
// Đơn từ thuộc Kết quả & công việc.
const PARENT: Partial<Record<NavigationTab, NavigationTab>> = {
  documents: 'library',
  consistency: 'library',
  compare: 'library',
  tasks: 'results',
};

// Thanh bên (Đợt 1, khung mới 20/11): chỉ điều hướng; chân là khối Kho tri thức (số thật từ máy chủ).
// Chọn không gian, Lịch sử, thông báo, tài khoản nằm ở thanh trên (Topbar).
export const Header: React.FC<SidebarProps> = ({
  health, activeTab, onTabChange, user, isMobileDrawerOpen = false, onToggleMobileDrawer, onOpenPalette, onOpenAdmin, docCount, chunkCount, top, bottom,
}) => {
  const uid = user?.email || user?.username;
  const [research, setResearch] = useState(researchMode(uid));
  useEffect(() => setResearch(researchMode(uid)), [uid]);
  useEffect(() => {
    const on = (e: Event) => setResearch(!!(e as CustomEvent).detail);
    window.addEventListener(RESEARCH_EVENT, on);
    return () => window.removeEventListener(RESEARCH_EVENT, on);
  }, []);
  // Thu gọn thanh bên thành dải biểu tượng (chỉ màn rộng); nhớ lựa chọn; Ctrl+B để bật/tắt.
  const [rail, setRail] = useState(() => { try { return localStorage.getItem('orchestriq-sb-rail') === '1'; } catch { return false; } });
  const toggleRail = () => setRail(v => { const n = !v; try { localStorage.setItem('orchestriq-sb-rail', n ? '1' : '0'); } catch { /* chế độ riêng tư */ } return n; });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b' && !e.shiftKey && !e.altKey) { e.preventDefault(); toggleRail(); } };
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey);
  }, []);
  // Phóng đại quanh con trỏ khi thu gọn, giữ nguyên tâm từng ô để thanh bên không lệch trục.
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
        icon.style.setProperty('--mag', (1 + .65 * (1 + Math.cos(Math.PI * distance)) / 2).toFixed(3));
      });
      magFrame.current = 0;
    });
  };
  const unmagnify = (e: React.MouseEvent<HTMLElement>) => {
    cancelAnimationFrame(magFrame.current);
    e.currentTarget.querySelectorAll<HTMLElement>('.sb-ico').forEach(icon => icon.style.removeProperty('--mag'));
  };
  useEffect(() => () => cancelAnimationFrame(magFrame.current), []);
  // chú thích nổi khi thanh bên thu gọn; cập nhật thẳng phần tử, không qua state
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
  const ollamaOk = !!health?.ollama_status?.includes('CONNECTED');

  const current = PARENT[activeTab] ?? activeTab;
  const showResearch = user?.role === 'admin' || research;
  const nav: { id: NavigationTab; label: string; Icon: typeof MessagesSquare; show: boolean; group?: string }[] = [
    // Nhóm 1: Làm việc hằng ngày
    { id: 'orchestration', label: 'Không gian làm việc', Icon: MessagesSquare, show: true, group: 'Làm việc' },
    { id: 'toolkit', label: 'Kỹ năng', Icon: Sparkles, show: true },
    { id: 'office', label: 'Văn phòng Agent', Icon: Bot, show: true },
    // Nhóm 2: Tri thức & Quản lý (giữ nguyên tên trang Tổng quan)
    { id: 'library', label: 'Tài liệu', Icon: FolderOpen, show: true, group: 'Tri thức & Quản lý' },
    { id: 'results', label: 'Kết quả & công việc', Icon: Inbox, show: true },
    { id: 'overview', label: 'Tổng quan', Icon: BarChart3, show: true },
    { id: 'organization', label: 'Tổ chức', Icon: Building2, show: !!user },
    // Nhóm 3: Nghiên cứu C1SE.27
    { id: 'evaluation', label: 'Phòng đánh giá', Icon: ClipboardCheck, show: showResearch, group: 'Nghiên cứu' },
    { id: 'benchmarks', label: 'Thực nghiệm', Icon: FlaskConical, show: showResearch },
    { id: 'rating', label: 'Chấm mù', Icon: EyeOff, show: showResearch },
  ];
  const go = (id: NavigationTab) => { onTabChange(id); if (isMobileDrawerOpen) onToggleMobileDrawer?.(); };

  // viên trượt đi theo mục đang mở
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
  }, [current, user?.role, rail, showResearch]);

  return (
    <>
      {isMobileDrawerOpen && <div className="sb-overlay" onClick={onToggleMobileDrawer} />}
      <aside className={`sb sb-fn${isMobileDrawerOpen ? ' is-open' : ''}${rail && !isMobileDrawerOpen ? ' is-rail' : ''}`} aria-label="Thanh điều hướng">
        <div className="sb-brand">
          <Link to="/" className="sb-logo" title="Về trang giới thiệu đề tài" aria-label="OrchestrIQ Studio, về trang giới thiệu"><BrandLogo size="sm" showSubtitle={false} /></Link>
          {onToggleMobileDrawer && isMobileDrawerOpen && <button className="sb-x" onClick={onToggleMobileDrawer} aria-label="Đóng thanh bên"><X size={18} /></button>}
          <div className="sb-tools">
            <button type="button" className="sb-icon sb-rail-btn" onClick={toggleRail} aria-pressed={rail} aria-label={rail ? 'Mở rộng thanh bên (Ctrl+B)' : 'Thu gọn thanh bên (Ctrl+B)'} title={rail ? 'Mở rộng (Ctrl+B)' : 'Thu gọn (Ctrl+B)'}>
              {rail ? <ChevronRight size={15} strokeWidth={2.4} /> : <ChevronLeft size={15} strokeWidth={2.4} />}
            </button>
          </div>
        </div>

        {onOpenAdmin && <PortalSwitch portal="research" onChange={p => p === 'admin' && onOpenAdmin()} />}
        {top}

        <div className="sb-scroll">
          {onOpenPalette && <button type="button" className="sb-search" onClick={onOpenPalette} aria-label="Tìm nhanh (Ctrl K)"><Search size={15} /><span>Tìm nhanh</span><kbd>Ctrl K</kbd></button>}
          <nav className="sb-nav" aria-label="Chức năng chính" ref={navRef} onMouseMove={magnify} onMouseLeave={unmagnify}>
            <span className="sb-glide" ref={glideRef} aria-hidden="true" />
            {nav.filter(n => n.show).map(({ id, label, Icon, group }) => (
              <React.Fragment key={id}>
                {group && <p className="sb-group">{group}</p>}
                <button onClick={() => go(id)} aria-label={label} aria-current={current === id ? 'page' : undefined} className={`sb-link${current === id ? ' is-on' : ''}`}
                  onMouseEnter={showTip} onFocus={showTip} onMouseLeave={hideTip} onBlur={hideTip}>
                  <span className="sb-ico" data-tone={id} aria-hidden="true"><Icon size={18} strokeWidth={2} /></span><span>{label}</span>
                </button>
              </React.Fragment>
            ))}
          </nav>
        </div>
        {rail && <span className="sb-tip" ref={tipRef} hidden aria-hidden="true" />}

        {bottom}
      </aside>
    </>
  );
};
