// Cài đặt: hồ sơ cá nhân (đổi họ tên, ảnh đại diện), bảo mật (đổi mật khẩu, quản lý phiên đăng nhập),
// giao diện sáng/tối, chế độ nhà nghiên cứu, kết nối nguồn tài liệu và thông tin hệ thống.
import React, { useEffect, useState } from 'react';
import {
  AuthSessionItem,
  changePassword,
  listSessions,
  revokeOtherSessions,
  sharedFolderStatus,
  syncSharedFolder,
  updateProfile,
} from '../services/api';
import {
  CheckCircle2,
  Cpu,
  FlaskConical,
  ImageUp,
  KeyRound,
  Library,
  Link2,
  LogOut,
  MonitorSmartphone,
  Moon,
  Palette,
  Save,
  Settings,
  ShieldCheck,
  Sun,
} from 'lucide-react';
import type { HealthResponse, User } from '../types';
import { researchMode, setResearchMode } from '../utils/researchMode';
import { Avatar } from './Avatar';
import { ToolHeader } from './analysis/shared';
import { serverDate } from '../utils/time';
import '../styles/pages-2b.css';

type Props = {
  user: User;
  theme: 'light' | 'dark';
  onThemeChange: (t: 'light' | 'dark') => void;
  onChangeAvatar: () => void;
  onUserChange?: (u: User) => void;
  onOpenLibrary: () => void;
  onChanged?: () => void;
  health?: HealthResponse | null;
  docCount?: number;
};

const dtf = new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' });

export const SettingsView: React.FC<Props> = ({
  user, theme, onThemeChange, onChangeAvatar, onUserChange, onOpenLibrary, onChanged, health, docCount,
}) => {
  const [research, setResearch] = useState(researchMode(user.email || user.username));
  const admin = user.role === 'admin';

  // ---- Cập nhật họ tên hiển thị ----
  const [displayName, setDisplayName] = useState(user.full_name || '');
  const [savingName, setSavingName] = useState(false);
  const [nameMsg, setNameMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null);
  useEffect(() => { setDisplayName(user.full_name || ''); }, [user.full_name]);

  const handleSaveName = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = displayName.trim();
    if (!trimmed) { setNameMsg({ tone: 'err', text: 'Vui lòng nhập họ và tên hiển thị.' }); return; }
    setSavingName(true); setNameMsg(null);
    try {
      const updated = await updateProfile(trimmed);
      onUserChange?.(updated);
      setNameMsg({ tone: 'ok', text: 'Đã cập nhật họ tên hiển thị.' });
    } catch (err: any) {
      setNameMsg({ tone: 'err', text: err.message || 'Không cập nhật được họ tên.' });
    } finally {
      setSavingName(false);
    }
  };

  // ---- Đổi mật khẩu ----
  const [curPw, setCurPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [savingPw, setSavingPw] = useState(false);
  const [pwMsg, setPwMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null);

  const handleChangePw = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwMsg(null);
    if (!curPw) { setPwMsg({ tone: 'err', text: 'Vui lòng nhập mật khẩu hiện tại.' }); return; }
    if (newPw.length < 8) { setPwMsg({ tone: 'err', text: 'Mật khẩu mới cần ít nhất 8 ký tự.' }); return; }
    if (newPw !== confirmPw) { setPwMsg({ tone: 'err', text: 'Mật khẩu nhập lại không khớp.' }); return; }
    setSavingPw(true);
    try {
      const r = await changePassword(curPw, newPw);
      setCurPw(''); setNewPw(''); setConfirmPw('');
      setPwMsg({
        tone: 'ok',
        text: r.revoked_sessions > 0
          ? `Đã đổi mật khẩu và tự động đăng xuất ${r.revoked_sessions} phiên trên thiết bị khác.`
          : 'Đã đổi mật khẩu thành công.',
      });
      void refreshSessions();
    } catch (err: any) {
      setPwMsg({ tone: 'err', text: err.message || 'Không thể đổi mật khẩu.' });
    } finally {
      setSavingPw(false);
    }
  };

  // ---- Phiên đăng nhập ----
  const [sessions, setSessions] = useState<AuthSessionItem[] | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [sessMsg, setSessMsg] = useState<string>('');
  const refreshSessions = async () => {
    try { setSessions(await listSessions()); } catch { setSessions([]); }
  };
  useEffect(() => { void refreshSessions(); }, [user.username]);

  const otherCount = (sessions ?? []).filter(s => !s.is_current).length;
  const handleRevokeOthers = async () => {
    setRevoking(true); setSessMsg('');
    try {
      const r = await revokeOtherSessions();
      setSessMsg(r.revoked_sessions > 0 ? `Đã đăng xuất ${r.revoked_sessions} phiên khác.` : 'Không có phiên nào khác để đăng xuất.');
      await refreshSessions();
    } catch (err: any) {
      setSessMsg(err.message || 'Không thể đăng xuất các thiết bị khác.');
    } finally {
      setRevoking(false);
    }
  };

  return (
    <main className="pg tl tone-overview set">
      <div className="pg-col">
        <ToolHeader Icon={Settings} title="Cài đặt" desc="Hồ sơ cá nhân, bảo mật tài khoản, giao diện, chế độ nhà nghiên cứu và nguồn tài liệu." />

        <section className="dz-card set-profile">
          <Avatar value={user.avatar ?? undefined} className="sb-avatar is-xl">{user.full_name.charAt(0)}</Avatar>
          <div className="set-profile-text">
            <h2>{user.full_name}</h2>
            <p>{user.email || user.username}</p>
            <span className={`set-role${admin ? ' is-admin' : ''}`}>{admin ? 'Quản trị hệ thống' : 'Người dùng'}</span>
          </div>
          <button type="button" className="btn btn-ghost" onClick={onChangeAvatar}><ImageUp size={15} />Đổi ảnh đại diện</button>
        </section>

        <div className="set-grid">
          <section className="dz-card set-card">
            <header><h3><ShieldCheck size={16} />Hồ sơ & Bảo mật tài khoản</h3></header>
            <form className="set-form" onSubmit={handleSaveName}>
              <label htmlFor="set-display-name">Họ và tên hiển thị</label>
              <div className="set-inline">
                <input id="set-display-name" type="text" maxLength={128} value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="Nhập họ và tên…" />
                <button type="submit" className="btn btn-dark is-sm" disabled={savingName || displayName.trim() === user.full_name}>
                  <Save size={14} />{savingName ? 'Đang lưu…' : 'Lưu tên'}
                </button>
              </div>
              {nameMsg && <p className={`set-feedback is-${nameMsg.tone}`} role={nameMsg.tone === 'err' ? 'alert' : 'status'}>
                {nameMsg.tone === 'ok' && <CheckCircle2 size={14} />}<span>{nameMsg.text}</span>
              </p>}
            </form>

            <hr className="set-divider" />

            <form className="set-form" onSubmit={handleChangePw}>
              <h4 className="set-sub"><KeyRound size={15} />Đổi mật khẩu</h4>
              <label htmlFor="set-pw-cur">Mật khẩu hiện tại</label>
              <input id="set-pw-cur" type="password" autoComplete="current-password" value={curPw} onChange={e => setCurPw(e.target.value)} placeholder="Nhập mật khẩu đang dùng" />
              <label htmlFor="set-pw-new">Mật khẩu mới <small>(tối thiểu 8 ký tự)</small></label>
              <input id="set-pw-new" type="password" autoComplete="new-password" value={newPw} onChange={e => setNewPw(e.target.value)} placeholder="Nhập mật khẩu mới" />
              <label htmlFor="set-pw-cf">Nhập lại mật khẩu mới</label>
              <input id="set-pw-cf" type="password" autoComplete="new-password" value={confirmPw} onChange={e => setConfirmPw(e.target.value)} placeholder="Xác nhận mật khẩu mới" />
              <button type="submit" className="btn btn-dark is-sm" disabled={savingPw || !curPw || !newPw || !confirmPw}>
                <KeyRound size={14} />{savingPw ? 'Đang cập nhật…' : 'Cập nhật mật khẩu'}
              </button>
              {pwMsg && <p className={`set-feedback is-${pwMsg.tone}`} role={pwMsg.tone === 'err' ? 'alert' : 'status'}>
                {pwMsg.tone === 'ok' && <CheckCircle2 size={14} />}<span>{pwMsg.text}</span>
              </p>}
            </form>
          </section>

          <section className="dz-card set-card">
            <header><h3><MonitorSmartphone size={16} />Phiên đăng nhập</h3></header>
            <p>Các trình duyệt hoặc thiết bị đang giữ phiên hoạt động của tài khoản này. Đổi mật khẩu sẽ tự động đăng xuất các phiên khác.</p>
            {sessions === null ? (
              <p className="set-note">Đang tải danh sách phiên…</p>
            ) : sessions.length === 0 ? (
              <p className="set-note">Không tìm thấy phiên đăng nhập nào.</p>
            ) : (
              <ul className="set-sessions">
                {sessions.slice(0, 6).map(s => (
                  <li key={s.session_id} className={s.is_current ? 'is-current' : ''}>
                    <div>
                      <b>{s.is_current ? 'Thiết bị hiện tại' : `Phiên ${s.session_id.slice(-6)}`}</b>
                      <small>Đăng nhập: {dtf.format(serverDate(s.created_at))} · Hết hạn: {dtf.format(serverDate(s.expires_at))}</small>
                    </div>
                    {s.is_current && <span className="set-badge-now">Đang dùng</span>}
                  </li>
                ))}
              </ul>
            )}
            <button type="button" className="btn btn-ghost is-sm" disabled={revoking || otherCount === 0} onClick={handleRevokeOthers}>
              <LogOut size={14} />{revoking ? 'Đang xử lý…' : otherCount > 0 ? `Đăng xuất ${otherCount} thiết bị khác` : 'Chỉ có phiên hiện tại'}
            </button>
            {sessMsg && <p className="set-feedback is-ok" role="status"><CheckCircle2 size={14} /><span>{sessMsg}</span></p>}
          </section>

          <section className="dz-card set-card">
            <header><h3><Palette size={16} />Hiển thị & Nghiên cứu</h3></header>
            <div className="set-seg" role="group" aria-label="Chọn giao diện">
              <button type="button" aria-pressed={theme === 'light'} onClick={() => onThemeChange('light')}><Sun size={14} />Sáng</button>
              <button type="button" aria-pressed={theme === 'dark'} onClick={() => onThemeChange('dark')}><Moon size={14} />Tối</button>
            </div>
            <h4 className="set-sub"><FlaskConical size={15} />Chế độ nhà nghiên cứu</h4>
            <p>Hiện nhóm Nghiên cứu (Phòng đánh giá, Thực nghiệm, Chấm mù) trên thanh bên. {admin ? 'Quản trị hệ thống luôn thấy nhóm này.' : 'Người dùng thường không cần các trang này.'}</p>
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
            <button type="button" className="btn btn-ghost is-sm" onClick={onOpenLibrary}>Mở Thư viện tài liệu</button>
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
            <button type="button" className="btn btn-dark is-sm" onClick={sync} disabled={busy}>{busy ? <span className="spin" /> : <Link2 size={14} />}Đồng bộ ngay</button></>
        : st && <p>Chưa có thư mục chung. Quản trị đặt biến <code>SHARED_FOLDER_PATH</code> cho backend (đường dẫn thư mục trên máy chủ) rồi khởi động lại.</p>}
      {res && <p className="set-note">Đã nạp {res.imported.length} tệp{res.skipped.length ? `, bỏ qua ${res.skipped.length} (${res.skipped.slice(0, 3).map(s => `${s.name}: ${s.reason}`).join('; ')}${res.skipped.length > 3 ? '…' : ''})` : ''}.</p>}
      {err && <p className="note is-error" role="alert">{err}</p>}
      <small className="set-note">Google Drive, SharePoint, email: chưa có, cần tài khoản dịch vụ của tổ chức.</small>
    </section>
  );
};
