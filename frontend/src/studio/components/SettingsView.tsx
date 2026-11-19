// Cài đặt (đợt 6, mục 2b): tài khoản, giao diện, chế độ nhà nghiên cứu, kết nối nguồn (chưa có), sửa nhãn tài liệu.
import React, { useState } from 'react';
import { FlaskConical, ImageUp, Library, Link2, Moon, Palette, Settings, Sun, UserRound } from 'lucide-react';
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
};

export const SettingsView: React.FC<Props> = ({ user, theme, onThemeChange, onChangeAvatar, onOpenLibrary }) => {
  const [research, setResearch] = useState(researchMode());
  const admin = user.role === 'admin';
  return (
    <main className="pg tl tone-overview set">
      <div className="pg-col">
        <ToolHeader Icon={Settings} title="Cài đặt" desc="Tài khoản, giao diện, các trang hiện trên thanh bên và kết nối nguồn tài liệu." />
        <div className="set-grid">
          <section className="dz-card set-card">
            <header><h3><UserRound size={16} />Tài khoản</h3></header>
            <div className="set-me"><Avatar value={user.avatar ?? undefined} className="sb-avatar is-lg">{user.full_name.charAt(0)}</Avatar>
              <span><b>{user.full_name}</b><small>{user.email || user.username}</small><small>{admin ? 'Quản trị hệ thống' : 'Người dùng'}</small></span></div>
            <button className="btn btn-ghost is-sm" onClick={onChangeAvatar}><ImageUp size={14} />Đổi ảnh đại diện</button>
          </section>

          <section className="dz-card set-card">
            <header><h3><Palette size={16} />Giao diện</h3></header>
            <div className="set-seg" role="group" aria-label="Chọn giao diện">
              <button type="button" aria-pressed={theme === 'light'} onClick={() => onThemeChange('light')}><Sun size={14} />Sáng</button>
              <button type="button" aria-pressed={theme === 'dark'} onClick={() => onThemeChange('dark')}><Moon size={14} />Tối</button>
            </div>
          </section>

          <section className="dz-card set-card">
            <header><h3><FlaskConical size={16} />Chế độ nhà nghiên cứu</h3></header>
            <p>Hiện nhóm Nghiên cứu (Thực nghiệm A/B/C, Phòng đánh giá, Chấm mù) trên thanh bên. {admin ? 'Quản trị hệ thống luôn thấy nhóm này.' : 'Người dùng thường không cần các trang này.'}</p>
            <label className="set-switch"><input type="checkbox" checked={research || admin} disabled={admin}
              onChange={e => { setResearch(e.target.checked); setResearchMode(e.target.checked); }} />
              <span>{research || admin ? 'Đang hiện' : 'Đang ẩn'}</span></label>
            <small className="set-note">Đây là tùy chọn hiển thị trên trình duyệt này, không phải phân quyền.</small>
          </section>

          <section className="dz-card set-card">
            <header><h3><Library size={16} />Nhãn tài liệu</h3></header>
            <p>Hệ thống tự nhận loại tài liệu khi tải lên (hợp đồng, quy chế, nội quy…). Nếu nhận sai, sửa ở Thư viện tài liệu.</p>
            <button className="btn btn-ghost is-sm" onClick={onOpenLibrary}>Mở Thư viện tài liệu</button>
          </section>

          <section className="dz-card set-card set-soon">
            <header><h3><Link2 size={16} />Kết nối nguồn tài liệu</h3></header>
            <p>Thư mục chung, Google Drive, SharePoint: <b>chưa có</b> (đợt 10 của lộ trình). Hiện tải tài liệu bằng kéo thả hoặc nút “Thêm tài liệu”.</p>
          </section>
        </div>
      </div>
    </main>
  );
};
