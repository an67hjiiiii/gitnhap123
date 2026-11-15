// Trang Người dùng (chỉ ADMIN): xem mọi tài khoản, tạo tài khoản cho nhân viên, đổi vai trò, khóa/mở khóa,
// đặt lại mật khẩu tạm, đăng xuất mọi phiên. Mật khẩu tạm chỉ hiện một lần để admin chép đưa cho người dùng.
// Backend chặn: tự hạ quyền / tự khóa mình, và hạ quyền hay khóa quản trị viên đang hoạt động cuối cùng.
import React, { useEffect, useMemo, useState } from 'react';
import { Check, Copy, KeyRound, LogOut, Lock, Plus, RefreshCw, Search, ShieldCheck, Unlock, UserPlus, Users } from 'lucide-react';
import {
  AdminUser, createAdminUser, listAdminUsers, resetAdminUserPassword, revokeAdminUserSessions, updateAdminUser,
} from '../services/api';
import { serverDate } from '../utils/time';
import { ToolHeader } from './analysis/shared';
import './profile/tools.css';

const fmt = (s: string | null) => (s ? serverDate(s).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' }) : 'Chưa đăng nhập');
const who = (u: AdminUser) => u.email || u.username || u.user_id;

export function UsersAdminView({ currentUserId }: { currentUserId?: string }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [secret, setSecret] = useState<{ who: string; password: string } | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = async (query = q) => {
    setLoading(true);
    try { setUsers((await listAdminUsers(query)).users); setError(''); } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  };
  useEffect(() => { void refresh(''); }, []);
  useEffect(() => { const t = window.setTimeout(() => void refresh(q), 250); return () => window.clearTimeout(t); }, [q]);

  const stats = useMemo(() => ({
    active: users.filter(u => u.status === 'ACTIVE').length,
    admins: users.filter(u => u.role === 'ADMIN' && u.status === 'ACTIVE').length,
    online: users.filter(u => u.active_sessions > 0).length,
  }), [users]);

  // chạy một thao tác trên một dòng, báo kết quả rồi tải lại danh sách
  const act = async (u: AdminUser, run: () => Promise<string | void>) => {
    setBusy(u.user_id); setError(''); setNotice('');
    try { const msg = await run(); if (msg) setNotice(msg); await refresh(); } catch (e: any) { setError(e.message); } finally { setBusy(null); }
  };
  const toggleRole = (u: AdminUser) => act(u, async () => {
    const role = u.role === 'ADMIN' ? 'USER' : 'ADMIN';
    if (!confirm(`${role === 'ADMIN' ? 'Cấp quyền quản trị cho' : 'Bỏ quyền quản trị của'} ${who(u)}?`)) return;
    await updateAdminUser(u.user_id, { role });
    return `Đã ${role === 'ADMIN' ? 'cấp quyền quản trị cho' : 'bỏ quyền quản trị của'} ${who(u)}.`;
  });
  const toggleStatus = (u: AdminUser) => act(u, async () => {
    const status = u.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE';
    if (status === 'DISABLED' && !confirm(`Khóa ${who(u)}? Người này bị đăng xuất ngay và không đăng nhập được cho tới khi mở khóa. Dữ liệu vẫn giữ nguyên.`)) return;
    await updateAdminUser(u.user_id, { status });
    return status === 'DISABLED' ? `Đã khóa ${who(u)} và đăng xuất mọi phiên.` : `Đã mở khóa ${who(u)}.`;
  });
  const resetPassword = (u: AdminUser) => act(u, async () => {
    if (!confirm(`Đặt mật khẩu tạm mới cho ${who(u)}? Mật khẩu cũ hết hiệu lực và mọi phiên bị đăng xuất.`)) return;
    const r = await resetAdminUserPassword(u.user_id);
    setSecret({ who: who(u), password: r.temporary_password });
  });
  const revoke = (u: AdminUser) => act(u, async () => {
    const r = await revokeAdminUserSessions(u.user_id);
    return r.revoked ? `Đã đăng xuất ${r.revoked} phiên của ${who(u)}.` : `${who(u)} không có phiên nào đang mở.`;
  });

  return (
    <main className="pg tl tone-overview ua-page">
      <div className="pg-col tv-col">
        <ToolHeader Icon={Users} title="Người dùng" desc="Tạo tài khoản cho nhân viên, phân quyền quản trị, khóa tài khoản khi người dùng nghỉ việc và đặt lại mật khẩu. Mọi thao tác được ghi vào nhật ký hoạt động."
          right={<button className="btn btn-dark" onClick={() => setCreating(v => !v)}><UserPlus size={15} />Thêm tài khoản</button>} />
        {error && <p className="note is-error" role="alert">{error}</p>}
        {notice && <p className="note" role="status">{notice}</p>}
        {secret && <SecretBox who={secret.who} password={secret.password} onClose={() => setSecret(null)} />}
        {creating && <CreateForm onDone={(u, pw) => { setCreating(false); if (pw) setSecret({ who: who(u), password: pw }); else setNotice(`Đã tạo tài khoản ${who(u)}.`); void refresh(); }} onCancel={() => setCreating(false)} />}

        <div className="dp-kpis ua-kpis">
          <div><b>{users.length}</b><span>tài khoản{q ? ' khớp tìm kiếm' : ''}</span></div>
          <div><b>{stats.active}</b><span>đang hoạt động</span></div>
          <div><b>{stats.admins}</b><span>quản trị viên</span></div>
          <div><b>{stats.online}</b><span>đang có phiên đăng nhập</span></div>
        </div>

        <section className="dz-card">
          <header><h3><Users size={16} />Danh sách tài khoản</h3>
            <span className="ua-tools">
              <label className="ua-search"><Search size={14} aria-hidden="true" /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm theo email, tên" aria-label="Tìm tài khoản" /></label>
              <button className="btn btn-ghost is-sm" onClick={() => refresh()}><RefreshCw size={14} />Làm mới</button>
            </span>
          </header>
          {loading && !users.length ? <p className="is-muted">Đang tải…</p> : !users.length ? <p className="is-muted">Không có tài khoản nào khớp.</p> :
            <div className="tbl tv-table"><table><thead><tr><th>Người dùng</th><th>Vai trò</th><th>Trạng thái</th><th>Đăng nhập gần nhất</th><th>Tài liệu</th><th>Lượt hỏi</th><th>Thao tác</th></tr></thead><tbody>
              {users.map(u => {
                const me = u.user_id === currentUserId;
                return <tr key={u.user_id} className={u.status === 'DISABLED' ? 'ua-off' : ''}>
                  <td><span className="ua-person"><span className="ua-av" style={{ ['--h' as string]: String([...u.user_id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7)) }} aria-hidden="true">{(u.display_name || u.email || '?').trim().split(/\s+/).slice(-1)[0][0]?.toUpperCase()}</span><span><b>{u.display_name}{me && <span className="ua-me"> (bạn)</span>}</b><small className="is-muted">{who(u)}</small></span></span></td>
                  <td><span className={`kb-status ${u.role === 'ADMIN' ? 'is-info' : ''}`}>{u.role === 'ADMIN' ? 'Quản trị' : 'Người dùng'}</span></td>
                  <td><span className={`kb-status ${u.status === 'ACTIVE' ? 'is-ok' : 'is-error'}`}>{u.status === 'ACTIVE' ? 'Hoạt động' : 'Đã khóa'}</span>
                    {u.active_sessions > 0 && <small className="is-muted"> · {u.active_sessions} phiên</small>}</td>
                  <td>{fmt(u.last_login_at)}</td>
                  <td>{u.source_count}</td>
                  <td>{u.run_count}</td>
                  <td className="ua-acts">
                    <button className="icon-btn is-sm" disabled={me || busy === u.user_id} onClick={() => toggleRole(u)} title={me ? 'Không tự đổi vai trò của mình' : u.role === 'ADMIN' ? 'Bỏ quyền quản trị' : 'Cấp quyền quản trị'} aria-label={`${u.role === 'ADMIN' ? 'Bỏ' : 'Cấp'} quyền quản trị: ${who(u)}`}><ShieldCheck size={15} /></button>
                    <button className="icon-btn is-sm" disabled={me || busy === u.user_id} onClick={() => toggleStatus(u)} title={me ? 'Không tự khóa tài khoản của mình' : u.status === 'ACTIVE' ? 'Khóa tài khoản' : 'Mở khóa'} aria-label={`${u.status === 'ACTIVE' ? 'Khóa' : 'Mở khóa'}: ${who(u)}`}>{u.status === 'ACTIVE' ? <Lock size={15} /> : <Unlock size={15} />}</button>
                    <button className="icon-btn is-sm" disabled={busy === u.user_id} onClick={() => resetPassword(u)} title="Đặt lại mật khẩu tạm" aria-label={`Đặt lại mật khẩu: ${who(u)}`}><KeyRound size={15} /></button>
                    <button className="icon-btn is-sm" disabled={busy === u.user_id || !u.active_sessions} onClick={() => revoke(u)} title="Đăng xuất mọi phiên" aria-label={`Đăng xuất mọi phiên: ${who(u)}`}><LogOut size={15} /></button>
                  </td>
                </tr>;
              })}
            </tbody></table></div>}
        </section>
      </div>
    </main>
  );
}

function CreateForm({ onDone, onCancel }: { onDone: (u: AdminUser, temporary: string | null) => void; onCancel: () => void }) {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState<'USER' | 'ADMIN'>('USER');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError('');
    try {
      const r = await createAdminUser({ email: email.trim(), display_name: name.trim() || undefined, role, password: password || undefined });
      onDone(r.user, r.temporary_password);
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  };
  return (
    <form className="dz-card ua-create" onSubmit={submit}>
      <header><h3><UserPlus size={16} />Thêm tài khoản</h3></header>
      <div className="ua-grid">
        <label className="tv-field"><span>Email</span><input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="ten@congty.vn" autoComplete="off" /></label>
        <label className="tv-field"><span>Tên hiển thị</span><input value={name} onChange={e => setName(e.target.value)} maxLength={128} placeholder="Nguyễn Văn A" /></label>
        <label className="tv-field"><span>Vai trò</span><select value={role} onChange={e => setRole(e.target.value as 'USER' | 'ADMIN')}><option value="USER">Người dùng</option><option value="ADMIN">Quản trị</option></select></label>
        <label className="tv-field"><span>Mật khẩu (để trống thì tạo mật khẩu tạm)</span><input type="password" minLength={8} value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" /></label>
      </div>
      {error && <p className="note is-error" role="alert">{error}</p>}
      <div className="ua-row"><button className="btn btn-dark" disabled={busy || !email.trim()}>{busy ? <span className="spin" /> : <Plus size={15} />}Tạo tài khoản</button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Hủy</button></div>
    </form>
  );
}

function SecretBox({ who, password, onClose }: { who: string; password: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <section className="dz-card ua-secret" role="alert">
      <header><h3><KeyRound size={16} />Mật khẩu tạm của {who}</h3></header>
      <p className="is-muted">Chép và gửi riêng cho người dùng. Mật khẩu này chỉ hiện một lần; đóng hộp này là không xem lại được.</p>
      <div className="ua-row"><code className="ua-pw">{password}</code>
        <button className="btn btn-ghost is-sm" onClick={async () => { await navigator.clipboard?.writeText(password).catch(() => undefined); setCopied(true); }}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Đã chép' : 'Chép'}</button>
        <button className="btn btn-dark is-sm" onClick={onClose}>Đã lưu, đóng</button></div>
    </section>
  );
}
