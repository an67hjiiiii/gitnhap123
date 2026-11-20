// Cài đặt (đợt 6, mục 2b): tài khoản, giao diện, chế độ nhà nghiên cứu, kết nối nguồn (chưa có), sửa nhãn tài liệu.
import React, { useEffect, useState } from 'react';
import { sharedFolderStatus, syncSharedFolder } from '../services/api';
import { Cpu, FlaskConical, ImageUp, Library, Link2, Moon, Palette, Settings, Sun } from 'lucide-react';
import type { HealthResponse } from '../types';
import { researchMode, setResearchMode } from '../utils/researchMode';
import { Avatar } from './Avatar';
import { ToolHeader } from './analysis/shared';
import '../styles/pages-2b.css';

type Props = {
  user: { full_name: string; username?: string; email?: string; role?: string; avatar?: string | null };
  theme: 'light' | 'dark';
  onThemeChange: (t: 'light' | 'dark') => void;
  onChangeAvatar: () => void;
  onOpenLibrary: () => void;
  onChanged?: () => void;
  health?: HealthResponse | null;
  docCount?: number;
};

export const SettingsView: React.FC<Props> = ({ user, theme, onThemeChange, onChangeAvatar, onOpenLibrary, onChanged, health, docCount }) => {
  const [research, setResearch] = useState(researchMode(user.email || user.username));
  const admin = user.role === 'admin';
  return (
    <main className="pg tl tone-overview set">
      <div className="pg-col">
        <ToolHeader Icon={Settings} title="Cài đặt" desc="Tài khoản, giao diện, các trang hiện trên thanh bên và kết nối nguồn tài liệu." />
        <section className="dz-card set-profile">
          <Avatar value={user.avatar ?? undefined} className="sb-avatar is-xl">{user.full_name.charAt(0)}</Avatar>
          <div className="set-profile-text"><h2>{user.full_name}</h2><p>{user.email || user.username}</p>
            <span className={`set-role${admin ? ' is-admin' : ''}`}>{admin ? 'Quản trị hệ thống' : 'Người dùng'}</span></div>
          <button className="btn btn-ghost" onClick={onChangeAvatar}><ImageUp size={15} />Đổi ảnh đại diện</button>
        </section>
        <div className="set-grid">
          <section className="dz-card set-card">
            <header><h3><Palette size={16} />Hiển thị</h3></header>
            <div className="set-seg" role="group" aria-label="Chọn giao diện">
              <button type="button" aria-pressed={theme === 'light'} onClick={() => onThemeChange('light')}><Sun size={14} />Sáng</button>
              <button type="button" aria-pressed={theme === 'dark'} onClick={() => onThemeChange('dark')}><Moon size={14} />Tối</button>
            </div>
            <h4 className="set-sub"><FlaskConical size={15} />Chế độ nhà nghiên cứu</h4>
            <p>Hiện nhóm Nghiên cứu (Thực nghiệm A/B/C, Phòng đánh giá, Chấm mù) trên thanh bên. {admin ? 'Quản trị hệ thống luôn thấy nhóm này.' : 'Người dùng thường không cần các trang này.'}</p>
            <label className="set-switch"><input type="checkbox" checked={research || admin} disabled={admin}
              onChange={e => { setResearch(e.target.checked); setResearchMode(e.target.checked, user.email || user.username); }} />
              <span>{research || admin ? 'Đang hiện' : 'Đang ẩn'}</span></label>
            <small className="set-note">Đây là tùy chọn hiển thị trên trình duyệt này, không phải phân quyền.</small>
          </section>

          <section className="dz-card set-card">
            <header><h3><Cpu size={16} />Hệ thống</h3></header>
            <dl className="set-sys">
              <div><dt>Mô hình trả lời</dt><dd>{health?.ollama_model || 'Chưa rõ'} <span className={`set-dot${health?.ollama_status === 'CONNECTED' ? ' is-ok' : ''}`}>{health ? (health.ollama_status === 'CONNECTED' ? 'đang chạy' : 'chưa kết nối') : 'đang kiểm tra'}</span></dd></div>
              <div><dt>Cơ sở dữ liệu</dt><dd>{health?.database_type || 'Chưa rõ'}</dd></div>
              <div><dt>Tài liệu trong không gian này</dt><dd>{docCount ?? 0}</dd></div>
              <div><dt>Nơi xử lý</dt><dd>Máy chủ của bạn, không gửi ra ngoài</dd></div>
            </dl>
          </section>

          <section className="dz-card set-card">
            <header><h3><Library size={16} />Nhãn tài liệu</h3></header>
            <p>Hệ thống tự nhận loại tài liệu khi tải lên (hợp đồng, quy chế, nội quy…). Nếu nhận sai, sửa ở Thư viện tài liệu.</p>
            <button className="btn btn-ghost is-sm" onClick={onOpenLibrary}>Mở Thư viện tài liệu</button>
          </section>

          <SharedFolderCard onDone={onChanged} />
        </div>
      </div>
    </main>
  );
};

// Kết nối nguồn: thư mục chung trên máy chủ. Google Drive, SharePoint cần tài khoản dịch vụ của tổ chức nên chưa làm.
const SharedFolderCard: React.FC<{ onDone?: () => void }> = ({ onDone }) => {
  const [st, setSt] = useState<{ configured: boolean; folder?: string; files?: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ imported: string[]; skipped: { name: string; reason: string }[] } | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => { sharedFolderStatus().then(setSt).catch(e => setErr(e.message)); }, []);
  const sync = async () => {
    setBusy(true); setErr('');
    try { const r = await syncSharedFolder(); setRes(r); onDone?.(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <section className="dz-card set-card">
      <header><h3><Link2 size={16} />Kết nối nguồn tài liệu</h3></header>
      {st?.configured
        ? <><p>Thư mục chung <b>{st.folder}</b> trên máy chủ: {st.files} tệp nạp được. Đồng bộ để đưa tệp mới vào kho cá nhân; tệp đã có (cùng tên) được bỏ qua.</p>
            <button className="btn btn-dark is-sm" onClick={sync} disabled={busy}>{busy ? <span className="spin" /> : <Link2 size={14} />}Đồng bộ ngay</button></>
        : st && <p>Chưa có thư mục chung. Quản trị đặt biến <code>SHARED_FOLDER_PATH</code> cho backend (đường dẫn thư mục trên máy chủ) rồi khởi động lại.</p>}
      {res && <p className="set-note">Đã nạp {res.imported.length} tệp{res.skipped.length ? `, bỏ qua ${res.skipped.length} (${res.skipped.slice(0, 3).map(s => `${s.name}: ${s.reason}`).join('; ')}${res.skipped.length > 3 ? '…' : ''})` : ''}.</p>}
      {err && <p className="note is-error" role="alert">{err}</p>}
      <small className="set-note">Google Drive, SharePoint, email: chưa có, cần tài khoản dịch vụ của tổ chức.</small>
    </section>
  );
};
