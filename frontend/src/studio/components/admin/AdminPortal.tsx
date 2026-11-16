// Admin Portal: giao diện quản trị tách khỏi giao diện nghiên cứu (không robot, không khung chat).
// Bốn việc của quản trị viên: giám sát hệ thống, tài khoản & phân quyền, CSDL & nhật ký kiểm toán, cấu hình AI.
import React, { useEffect, useState } from 'react';
import { Activity, Cpu, Database, FlaskConical, LogOut, Menu, Moon, ShieldCheck, SlidersHorizontal, Sun, Users, X } from 'lucide-react';
import { User } from '../../types';
import { BrandLogo } from '../BrandLogo';
import { UsersAdminView } from '../UsersAdminView';
import { DatabaseExplorer } from '../DatabaseExplorer';
import { SystemHealth } from './SystemHealth';
import { AuditLog } from './AuditLog';
import { AiSettings } from './AiSettings';
import { StudioBackdrop } from '../StudioMotion';
import { Avatar } from '../Avatar';
import '../../styles/admin-portal.css';

type Page = 'health' | 'users' | 'data' | 'ai';
const NAV: { id: Page; label: string; desc: string; Icon: React.ComponentType<{ size?: number }> }[] = [
  { id: 'health', label: 'Giám sát hệ thống', desc: 'CPU, RAM, Ollama, CSDL', Icon: Activity },
  { id: 'users', label: 'Tài khoản & phân quyền', desc: 'Tạo, khóa, đổi vai trò', Icon: Users },
  { id: 'data', label: 'CSDL & kiểm toán', desc: 'Nhật ký: ai làm gì, lúc nào', Icon: Database },
  { id: 'ai', label: 'Cấu hình AI', desc: 'Mô hình, tham số điều phối', Icon: SlidersHorizontal },
];

/** Nút chuyển giữa giao diện Nghiên cứu và Bảng điều khiển quản trị (chỉ quản trị viên thấy). */
export function PortalSwitch({ portal, onChange }: { portal: 'research' | 'admin'; onChange: (p: 'research' | 'admin') => void }) {
  return (
    <div className={`portal-switch is-${portal}`} role="group" aria-label="Chọn giao diện">
      <i className="portal-thumb" aria-hidden="true" />
      <button type="button" aria-pressed={portal === 'research'} onClick={() => onChange('research')}><FlaskConical size={14} />Nghiên cứu</button>
      <button type="button" aria-pressed={portal === 'admin'} onClick={() => onChange('admin')}><ShieldCheck size={14} />Quản trị</button>
    </div>
  );
}

export function AdminPortal({ user, theme, onThemeChange, onLogout, onExit }: {
  user: User; theme: 'light' | 'dark'; onThemeChange: (t: 'light' | 'dark', at?: { x: number; y: number }) => void; onLogout: () => void; onExit: () => void;
}) {
  const [page, setPage] = useState<Page>(() => { try { return (localStorage.getItem('orchestriq-admin-page') as Page) || 'health'; } catch { return 'health'; } });
  const [dataTab, setDataTab] = useState<'audit' | 'db'>('audit');
  const [drawer, setDrawer] = useState(false);
  useEffect(() => { try { localStorage.setItem('orchestriq-admin-page', page); } catch { /* chế độ riêng tư */ } }, [page]);
  const go = (p: Page) => { setPage(p); setDrawer(false); };
  const cur = NAV.find(n => n.id === page)!;

  return (
    <div className="ap">
      <StudioBackdrop />
      {drawer && <div className="ap-overlay" onClick={() => setDrawer(false)} />}
      <aside className={`ap-side${drawer ? ' is-open' : ''}`} aria-label="Điều hướng quản trị">
        <div className="ap-brand">
          <BrandLogo size="sm" showSubtitle={false} theme="dark" />
          <span className="ap-chip">Quản trị</span>
          <button className="ap-x" onClick={() => setDrawer(false)} aria-label="Đóng menu"><X size={18} /></button>
        </div>
        <PortalSwitch portal="admin" onChange={p => p === 'research' && onExit()} />
        <p className="ap-group">Việc của quản trị viên</p>
        <nav className="ap-nav">{NAV.map(({ id, label, desc, Icon }) => (
          <button key={id} type="button" className={page === id ? 'is-on' : ''} aria-current={page === id ? 'page' : undefined} onClick={() => go(id)}>
            <span className="ap-nav-ico"><Icon size={17} /></span><span className="ap-nav-t"><b>{label}</b><small>{desc}</small></span>
          </button>))}</nav>
        <div className="ap-side-foot">
          <div className="ap-me"><Avatar value={user.avatar} className="ap-av">{user.full_name.charAt(0)}</Avatar><span><b>{user.full_name}</b><small>Quản trị viên</small></span>
            <button className="ap-icon" onClick={e => onThemeChange(theme === 'dark' ? 'light' : 'dark', { x: e.clientX, y: e.clientY })} aria-label={theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'} title={theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}</button>
            <button className="ap-icon" onClick={onLogout} aria-label="Đăng xuất" title="Đăng xuất"><LogOut size={16} /></button>
          </div>
        </div>
      </aside>

      <main className="ap-main">
        <div className="ap-mobilebar"><button className="ap-icon" onClick={() => setDrawer(true)} aria-label="Mở menu quản trị"><Menu size={20} /></button><b>{cur.label}</b><Cpu size={16} aria-hidden="true" /></div>
        {page === 'health' && <SystemHealth onOpenAudit={() => { setDataTab('audit'); go('data'); }} />}
        {page === 'users' && <div className="ap-embed"><UsersAdminView currentUserId={String(user.id)} /></div>}
        {page === 'data' && <div className="ap-page">
          <header className="ap-head"><div><p className="ap-kicker">Bảng điều khiển quản trị</p><h1>CSDL & nhật ký kiểm toán</h1><p>Theo dõi thao tác của mọi tài khoản và xem dữ liệu từng bảng (không hiện mật khẩu, token).</p></div>
            <div className="ap-tabs" role="tablist">
              <button role="tab" aria-selected={dataTab === 'audit'} className={dataTab === 'audit' ? 'is-on' : ''} onClick={() => setDataTab('audit')}>Nhật ký kiểm toán</button>
              <button role="tab" aria-selected={dataTab === 'db'} className={dataTab === 'db' ? 'is-on' : ''} onClick={() => setDataTab('db')}>Dữ liệu các bảng</button>
            </div></header>
          {dataTab === 'audit' ? <AuditLog /> : <div className="ap-embed is-flush"><DatabaseExplorer /></div>}
        </div>}
        {page === 'ai' && <AiSettings />}
      </main>
    </div>
  );
}
