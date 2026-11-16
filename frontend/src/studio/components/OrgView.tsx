// Trang Tổ chức: tạo hoặc tham gia không gian tổ chức; khi đang mở một không gian thì quản lý thành viên, phòng ban,
// lời mời, yêu cầu chờ duyệt và mức mật / chia sẻ của tài liệu. Mọi quyền do backend quyết định (app/core/access.py);
// giao diện chỉ ẩn bớt nút người dùng chắc chắn không được bấm, lỗi 403 từ máy chủ vẫn được hiện nguyên văn.
import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Building2, Check, Copy, DoorOpen, KeyRound, LayoutGrid, Link2, LogIn, Plus, RefreshCw, Share2, ShieldCheck, Trash2, UserCheck, UserPlus, Users, X } from 'lucide-react';
import {
  CLASS_HINT, CLASS_LABEL, Classification, LEVEL_LABEL, MemberLevel, MyInvite, OrgDetail, OrgInvite, OrgShare, OrgSpace, SETTABLE,
  answerInvite, approveMember, createDepartment, createJoinToken, createSpace, deleteDepartment, getSpace, inviteByEmail, isOrgId, joinSpace,
  leaveSpace, listInvites, listMySpaces, listShares, myInvites, removeMember, revokeInvite, shareSource, unshare, updateMember, updateSource,
} from '../services/api';
import { DocumentInfo } from '../types';
import { ToolHeader } from './analysis/shared';
import { Avatar } from './Avatar';
import './profile/tools.css';
import '../styles/org.css';

const LEVELS: MemberLevel[] = ['STAFF', 'MANAGER', 'EXECUTIVE'];
const avatarHue = (id: string) => String([...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7));
// chữ cái của từ cuối là chữ (bỏ qua phần như "(thử)"), theo cách gọi tên tiếng Việt
const initial = (name: string) => {
  const words = (name || '').trim().split(/\s+/).filter(w => /^\p{L}/u.test(w));
  return words.length ? words[words.length - 1][0].toUpperCase() : '?';
};

export function ClassBadge({ value }: { value?: string | null }) {
  if (!value) return null;
  const c = value as Classification;
  return <span className={`og-class is-${c.toLowerCase()}`} title={CLASS_HINT[c]}>{CLASS_LABEL[c] ?? value}</span>;
}

interface OrgViewProps {
  workspaceId: number | string;
  docs: DocumentInfo[];
  onOpenSpace: (id: string) => void;
  onChanged: () => Promise<void> | void;
}

export function OrgView(props: OrgViewProps) {
  // đang ở trong một công ty vẫn mở được trang "Tất cả tổ chức" (tạo mới, tham gia, chuyển công ty) mà không phải đổi không gian
  const [showAll, setShowAll] = useState(false);
  useEffect(() => setShowAll(false), [props.workspaceId]);
  const inSpace = isOrgId(props.workspaceId);
  const open = (id: string) => { setShowAll(false); if (id !== props.workspaceId) props.onOpenSpace(id); };
  return inSpace && !showAll
    ? <SpaceManager key={props.workspaceId} spaceId={props.workspaceId as string} {...props} onShowAll={() => setShowAll(true)} />
    : <OrgHome onOpenSpace={open} onChanged={props.onChanged} currentId={inSpace ? String(props.workspaceId) : undefined}
        onBack={inSpace ? () => setShowAll(false) : undefined} />;
}

// ---------------- Danh sách tổ chức, lời mời, tạo mới, tham gia bằng mã (từ không gian cá nhân hoặc từ trong một công ty)
function OrgHome({ onOpenSpace, onChanged, currentId, onBack }: Pick<OrgViewProps, 'onOpenSpace' | 'onChanged'> & { currentId?: string; onBack?: () => void }) {
  const [spaces, setSpaces] = useState<OrgSpace[]>([]);
  const [invites, setInvites] = useState<MyInvite[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [name, setName] = useState('');
  const [deps, setDeps] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const load = () => Promise.all([listMySpaces().then(setSpaces), myInvites().then(setInvites)]).catch(e => setError(e.message));
  useEffect(() => { void load(); }, []);

  const run = async (fn: () => Promise<string | void>) => {
    setBusy(true); setError(''); setNotice('');
    try { const m = await fn(); if (m) setNotice(m); await load(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <main className="pg tl tone-overview og-page">
      <div className="pg-col tv-col">
        <ToolHeader Icon={Building2} title="Tổ chức" desc="Tạo không gian cho công ty hoặc bộ phận, mời đồng nghiệp và phân cấp Nhân viên, Trưởng phòng, Ban giám đốc. Mỗi người chỉ thấy và hỏi AI trên tài liệu thuộc phạm vi được phép."
          right={onBack && <button className="btn btn-ghost is-sm" onClick={onBack}><ArrowLeft size={14} />Quay lại {spaces.find(s => s.space_id === currentId)?.name ?? 'công ty đang mở'}</button>} />
        {error && <p className="note is-error" role="alert">{error}</p>}
        {notice && <p className="note" role="status">{notice}</p>}

        {invites.length > 0 && <section className="dz-card og-invites">
          <header><h3><UserPlus size={16} />Lời mời đang chờ bạn</h3></header>
          <ul className="og-list">{invites.map(i => <li key={i.invite_id}>
            <span className="og-li-main"><b>{i.space_name}</b><small>{i.inviter} mời bạn làm {LEVEL_LABEL[i.level]}</small></span>
            <span className="og-li-acts">
              <button className="btn btn-dark is-sm" disabled={busy} onClick={() => run(async () => { const r = await answerInvite(i.invite_id, 'accept'); await onChanged(); onOpenSpace(r.space_id); })}><Check size={14} />Tham gia</button>
              <button className="btn btn-ghost is-sm" disabled={busy} onClick={() => run(async () => { await answerInvite(i.invite_id, 'decline'); return 'Đã từ chối lời mời.'; })}>Từ chối</button>
            </span></li>)}</ul>
        </section>}

        <section className="dz-card">
          <header><h3><Building2 size={16} />Tổ chức của bạn</h3><button className="btn btn-ghost is-sm" onClick={() => void load()}><RefreshCw size={14} />Làm mới</button></header>
          {!spaces.length ? <p className="is-muted">Bạn chưa thuộc tổ chức nào. Tạo mới hoặc nhập mã mời bên dưới.</p> :
            <ul className="og-list">{spaces.map(s => <li key={s.space_id}>
              <span className="og-mark" aria-hidden="true">{initial(s.name)}</span>
              <span className="og-li-main"><b>{s.name}</b><small>{s.status === 'PENDING' ? 'Đang chờ duyệt' : `${LEVEL_LABEL[s.level]}${s.is_owner ? ' · Chủ không gian' : ''}`}</small></span>
              <span className="og-li-acts">{s.space_id === currentId
                ? <button className="btn btn-ghost is-sm" onClick={() => onOpenSpace(s.space_id)}><Check size={14} />Đang mở</button>
                : s.status === 'ACTIVE'
                ? <button className="btn btn-dark is-sm" onClick={() => onOpenSpace(s.space_id)}><LogIn size={14} />Mở</button>
                : <span className="kb-status is-warn">Chờ duyệt</span>}</span>
            </li>)}</ul>}
        </section>

        <div className="og-grid">
          <form className="dz-card" onSubmit={e => { e.preventDefault(); void run(async () => {
            const r = await createSpace(name.trim(), deps.split(',').map(d => d.trim()).filter(Boolean));
            setName(''); setDeps(''); await onChanged(); onOpenSpace(r.space_id);
          }); }}>
            <header><h3><Plus size={16} />Tạo không gian tổ chức</h3></header>
            <label className="tv-field"><span>Tên công ty / bộ phận</span><input required maxLength={120} value={name} onChange={e => setName(e.target.value)} placeholder="VD: Công ty Minh Long" /></label>
            <label className="tv-field"><span>Phòng ban (cách nhau bằng dấu phẩy, thêm sau được)</span><input value={deps} onChange={e => setDeps(e.target.value)} placeholder="Kinh doanh, Kế toán" /></label>
            <p className="is-muted og-small">Bạn sẽ là Chủ không gian và thuộc Ban giám đốc.</p>
            <div className="ua-row"><button className="btn btn-dark" disabled={busy || !name.trim()}><Plus size={15} />Tạo</button></div>
          </form>
          <form className="dz-card" onSubmit={e => { e.preventDefault(); void run(async () => {
            const r = await joinSpace(token.trim()); setToken('');
            return `Đã gửi yêu cầu vào "${r.space_name}". Bạn vào được sau khi Trưởng phòng hoặc Ban giám đốc duyệt.`;
          }); }}>
            <header><h3><KeyRound size={16} />Tham gia bằng mã hoặc link</h3></header>
            <label className="tv-field"><span>Mã mời (VD ABCD-EFGH) hoặc phần cuối của link</span><input required value={token} onChange={e => setToken(e.target.value)} placeholder="ABCD-EFGH" autoComplete="off" /></label>
            <p className="is-muted og-small">Vào bằng mã hoặc link luôn phải chờ duyệt; cấp bậc do người duyệt gán.</p>
            <div className="ua-row"><button className="btn btn-dark" disabled={busy || token.trim().length < 4}><LogIn size={15} />Gửi yêu cầu</button></div>
          </form>
        </div>
      </div>
    </main>
  );
}

// ---------------- Khi đang mở một không gian tổ chức
function SpaceManager({ spaceId, docs, onOpenSpace, onChanged, onShowAll }: OrgViewProps & { spaceId: string; onShowAll: () => void }) {
  const [space, setSpace] = useState<OrgDetail | null>(null);
  const [invites, setInvites] = useState<OrgInvite[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);

  const load = async () => {
    try {
      const s = await getSpace(spaceId); setSpace(s);
      if (s.me.level !== 'STAFF') setInvites(await listInvites(spaceId).catch(() => []));
    } catch (e: any) { setError(e.message); }
  };
  useEffect(() => { void load(); }, [spaceId]);
  useEffect(() => { if (!notice) return; const t = window.setTimeout(() => setNotice(''), 6000); return () => window.clearTimeout(t); }, [notice]);
  const run = async (fn: () => Promise<string | void>, refreshDocs = false) => {
    setBusy(true); setError(''); setNotice('');
    try { const m = await fn(); if (m) setNotice(m); await load(); if (refreshDocs) await onChanged(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const depName = useMemo(() => Object.fromEntries((space?.departments || []).map(d => [d.department_id, d.name])), [space]);
  if (!space) return <main className="pg tl tone-overview og-page"><div className="pg-col tv-col">{error ? <p className="note is-error" role="alert">{error}</p> : <p className="is-muted">Đang tải không gian…</p>}</div></main>;

  const me = space.me;
  const exec = me.level === 'EXECUTIVE';
  const manager = me.level === 'MANAGER';
  const active = space.members.filter(m => m.status === 'ACTIVE');
  const pending = space.members.filter(m => m.status === 'PENDING');
  const ownerCount = active.filter(m => m.is_owner).length;

  return (
    <main className="pg tl tone-overview og-page">
      <div className="pg-col tv-col">
        <ToolHeader Icon={Building2} title="Tổ chức" desc={`${space.name}: thành viên, phòng ban, lời mời và mức mật tài liệu. AI trong không gian này chỉ đọc tài liệu bạn được phép xem.`}
          right={<span className="og-me"><span className={`og-level is-${me.level.toLowerCase()}`}>{LEVEL_LABEL[me.level]}{me.is_owner ? ' · Chủ' : ''}</span>
            <button className="btn btn-ghost is-sm" disabled={busy} onClick={() => {
              if (!confirm(`Rời "${space.name}"? Bạn mất quyền xem tài liệu và hội thoại trong không gian này ngay lập tức.`)) return;
              void run(async () => { const r = await leaveSpace(spaceId); await onChanged(); onOpenSpace(''); return r.drafts ? `Đã rời. ${r.drafts} bản nháp được bàn giao.` : 'Đã rời không gian.'; });
            }}><DoorOpen size={14} />Rời</button>
            <button className="btn btn-ghost is-sm" onClick={onShowAll} title="Xem mọi tổ chức, tạo tổ chức mới hoặc tham gia bằng mã"><LayoutGrid size={14} />Tất cả tổ chức</button></span>} />
        {/* kết quả thao tác hiện nổi ở góc màn hình: nút bấm có thể nằm cuối trang, xa phần đầu */}
        {(error || notice) && <div className={`st-toast is-${error ? 'error' : 'ok'}`} role={error ? 'alert' : 'status'}>
          <span>{error || notice}</span><button onClick={() => { setError(''); setNotice(''); }} aria-label="Đóng thông báo">×</button></div>}

        <div className="dp-kpis og-kpis">
          <div><b>{active.length}</b><span>thành viên</span></div>
          <div><b>{space.departments.length}</b><span>phòng ban</span></div>
          <div><b>{docs.length}</b><span>tài liệu bạn xem được</span></div>
          <div><b>{pending.length}</b><span>yêu cầu chờ duyệt</span></div>
        </div>

        {pending.length > 0 && (exec || manager) && <section className="dz-card">
          <header><h3><UserCheck size={16} />Chờ duyệt</h3></header>
          <ul className="og-list">{pending.map(m => <PendingRow key={m.user_id} member={m} space={space} busy={busy}
            onApprove={(level, dep) => run(async () => { await approveMember(spaceId, m.user_id, level, dep); return `Đã duyệt ${m.display_name}.`; })}
            onReject={() => run(async () => { await removeMember(spaceId, m.user_id); return `Đã từ chối ${m.display_name}.`; })} />)}</ul>
        </section>}

        <section className="dz-card">
          <header><h3><Users size={16} />Thành viên</h3><button className="btn btn-ghost is-sm" onClick={() => void load()}><RefreshCw size={14} />Làm mới</button></header>
          <div className="tbl tv-table"><table><thead><tr><th>Thành viên</th><th>Phòng ban</th><th>Cấp bậc</th><th>Thao tác</th></tr></thead><tbody>
            {active.map(m => <MemberRow key={m.user_id} m={m} space={space} depName={depName} busy={busy} ownerCount={ownerCount}
              onSave={body => run(async () => { await updateMember(spaceId, m.user_id, body); return `Đã cập nhật ${m.display_name}.`; })}
              onRemove={() => {
                if (!confirm(`Gỡ ${m.display_name} khỏi không gian? Người này mất quyền ngay; bản nháp của họ được bàn giao cho Trưởng phòng hoặc Ban giám đốc.`)) return;
                void run(async () => { const r = await removeMember(spaceId, m.user_id); return r.drafts ? `Đã gỡ ${m.display_name}; bàn giao ${r.drafts} bản nháp.` : `Đã gỡ ${m.display_name}.`; });
              }} />)}
          </tbody></table></div>
        </section>

        {secret && <section className="dz-card ua-secret" role="alert">
          <header><h3><KeyRound size={16} />{secret.label}</h3></header>
          <p className="is-muted">Chỉ hiện một lần. Gửi riêng cho người cần mời; người vào bằng mã hoặc link phải chờ duyệt.</p>
          <div className="ua-row"><code className="ua-pw og-secret">{secret.value}</code><CopyButton text={secret.value} />
            <button className="btn btn-dark is-sm" onClick={() => setSecret(null)}>Đã lưu, đóng</button></div>
        </section>}
        {(exec || manager) && <InvitePanel space={space} invites={invites} busy={busy} depName={depName}
          onEmail={(email, level, dep) => run(async () => { await inviteByEmail(spaceId, email, level, dep); return `Đã gửi lời mời tới ${email}. Họ sẽ thấy trong chuông thông báo.`; })}
          onToken={kind => run(async () => {
            const r = await createJoinToken(spaceId, kind);
            setSecret(kind === 'CODE' ? { label: 'Mã mời', value: r.token } : { label: 'Link mời', value: `${window.location.origin}/studio?join=${encodeURIComponent(r.token)}` });
          })}
          onRevoke={id => run(async () => { await revokeInvite(spaceId, id); return 'Đã thu hồi lời mời.'; })} />}

        <DepartmentPanel space={space} exec={exec} busy={busy}
          onAdd={name => run(async () => { await createDepartment(spaceId, name); return `Đã thêm phòng ${name}.`; })}
          onDelete={(id, name) => run(async () => { await deleteDepartment(spaceId, id); return `Đã xóa phòng ${name}.`; })} />

        <DocumentPanel spaceId={spaceId} space={space} docs={docs} depName={depName} busy={busy}
          onChange={(id, classification) => run(async () => { await updateSource(spaceId, id, { classification }); return `Đã đổi mức mật thành ${CLASS_LABEL[classification]}.`; }, true)}
          onShare={(id, target) => run(async () => { await shareSource(spaceId, id, target); return 'Đã chia sẻ. Người nhận được báo qua chuông thông báo.'; })} />
      </div>
    </main>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return <button className="btn btn-ghost is-sm" onClick={async () => { await navigator.clipboard?.writeText(text).catch(() => undefined); setCopied(true); }}>
    {copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Đã chép' : 'Chép'}</button>;
}

function DepartmentSelect({ space, value, onChange, allowNone, disabled }: { space: OrgDetail; value: string | null; onChange: (v: string | null) => void; allowNone?: boolean; disabled?: boolean }) {
  return <select value={value ?? ''} disabled={disabled} onChange={e => onChange(e.target.value || null)} aria-label="Phòng ban">
    {allowNone && <option value="">Không thuộc phòng</option>}
    {!allowNone && !value && <option value="">Chọn phòng</option>}
    {space.departments.map(d => <option key={d.department_id} value={d.department_id}>{d.name}</option>)}
  </select>;
}

function PendingRow({ member, space, busy, onApprove, onReject }: {
  member: OrgDetail['members'][number]; space: OrgDetail; busy: boolean;
  onApprove: (level: MemberLevel, dep: string | null) => void; onReject: () => void;
}) {
  const exec = space.me.level === 'EXECUTIVE';
  const [level, setLevel] = useState<MemberLevel>('STAFF');
  const [dep, setDep] = useState<string | null>(member.department_id ?? (exec ? null : space.me.department_id));
  const needDep = level !== 'EXECUTIVE' && !dep;
  return <li>
    <Avatar value={member.avatar} className="ua-av" style={{ ['--h' as string]: avatarHue(member.user_id) }}>{initial(member.display_name)}</Avatar>
    <span className="og-li-main"><b>{member.display_name}</b><small>{member.email}</small></span>
    <span className="og-li-acts og-inline">
      <select value={level} disabled={!exec} onChange={e => setLevel(e.target.value as MemberLevel)} aria-label="Cấp bậc khi duyệt">
        {(exec ? LEVELS : ['STAFF' as MemberLevel]).map(l => <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}</select>
      {level !== 'EXECUTIVE' && <DepartmentSelect space={space} value={dep} onChange={setDep} disabled={!exec} />}
      <button className="btn btn-dark is-sm" disabled={busy || needDep} onClick={() => onApprove(level, level === 'EXECUTIVE' ? null : dep)}><Check size={14} />Duyệt</button>
      <button className="btn btn-ghost is-sm" disabled={busy} onClick={onReject}><X size={14} />Từ chối</button>
    </span>
  </li>;
}

function MemberRow({ m, space, depName, busy, ownerCount, onSave, onRemove }: {
  m: OrgDetail['members'][number]; space: OrgDetail; depName: Record<string, string>; busy: boolean; ownerCount: number;
  onSave: (body: { level: MemberLevel; department_id: string | null; is_owner: boolean }) => void; onRemove: () => void;
}) {
  const me = space.me;
  const exec = me.level === 'EXECUTIVE';
  const [editing, setEditing] = useState(false);
  const [level, setLevel] = useState<MemberLevel>(m.level);
  const [dep, setDep] = useState<string | null>(m.department_id);
  const [owner, setOwner] = useState(m.is_owner);
  const canRemove = exec ? !(m.is_owner && (!me.is_owner || ownerCount <= 1))
    : me.level === 'MANAGER' && m.level === 'STAFF' && m.department_id === me.department_id;
  return <tr>
    <td><span className="ua-person"><Avatar value={m.avatar} className="ua-av" style={{ ['--h' as string]: avatarHue(m.user_id) }}>{initial(m.display_name)}</Avatar>
      <span><b>{m.display_name}</b><small className="is-muted">{m.email}</small></span></span></td>
    <td>{editing && level !== 'EXECUTIVE' ? <DepartmentSelect space={space} value={dep} onChange={setDep} /> : (m.department_id ? depName[m.department_id] : <span className="is-muted">—</span>)}</td>
    <td>{editing
      ? <span className="og-inline"><select value={level} onChange={e => { const l = e.target.value as MemberLevel; setLevel(l); if (l !== 'EXECUTIVE') setOwner(false); }} aria-label="Cấp bậc">
          {LEVELS.map(l => <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}</select>
          {me.is_owner && level === 'EXECUTIVE' && <label className="og-check"><input type="checkbox" checked={owner} onChange={e => setOwner(e.target.checked)} />Chủ</label>}</span>
      : <span className={`og-level is-${m.level.toLowerCase()}`}>{LEVEL_LABEL[m.level]}{m.is_owner ? ' · Chủ' : ''}</span>}</td>
    <td className="ua-acts">{editing ? <>
        <button className="btn btn-dark is-sm" disabled={busy || (level !== 'EXECUTIVE' && !dep)} onClick={() => { onSave({ level, department_id: dep, is_owner: owner }); setEditing(false); }}><Check size={14} />Lưu</button>
        <button className="btn btn-ghost is-sm" onClick={() => { setEditing(false); setLevel(m.level); setDep(m.department_id); setOwner(m.is_owner); }}>Hủy</button></>
      : <>
        {exec && <button className="icon-btn is-sm" disabled={busy} onClick={() => setEditing(true)} title="Đổi cấp bậc, phòng ban" aria-label={`Đổi cấp bậc: ${m.display_name}`}><ShieldCheck size={15} /></button>}
        {canRemove && <button className="icon-btn is-sm is-danger" disabled={busy} onClick={onRemove} title="Gỡ khỏi không gian" aria-label={`Gỡ ${m.display_name}`}><Trash2 size={15} /></button>}
      </>}</td>
  </tr>;
}

function InvitePanel({ space, invites, busy, depName, onEmail, onToken, onRevoke }: {
  space: OrgDetail; invites: OrgInvite[]; busy: boolean; depName: Record<string, string>;
  onEmail: (email: string, level: MemberLevel, dep: string | null) => void; onToken: (kind: 'LINK' | 'CODE') => void; onRevoke: (id: string) => void;
}) {
  const exec = space.me.level === 'EXECUTIVE';
  const [email, setEmail] = useState('');
  const [level, setLevel] = useState<MemberLevel>('STAFF');
  const [dep, setDep] = useState<string | null>(exec ? space.departments[0]?.department_id ?? null : space.me.department_id);
  const live = invites.filter(i => !i.revoked);
  return <section className="dz-card">
    <header><h3><UserPlus size={16} />Mời thành viên</h3>
      <span className="og-inline"><button className="btn btn-ghost is-sm" disabled={busy} onClick={() => onToken('CODE')}><KeyRound size={14} />Tạo mã</button>
        <button className="btn btn-ghost is-sm" disabled={busy} onClick={() => onToken('LINK')}><Link2 size={14} />Tạo link</button></span></header>
    <form className="ua-grid og-invite" onSubmit={e => { e.preventDefault(); onEmail(email.trim(), level, level === 'EXECUTIVE' ? null : dep); setEmail(''); }}>
      <label className="tv-field"><span>Email tài khoản đã đăng ký</span><input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="dongnghiep@congty.vn" autoComplete="off" /></label>
      <label className="tv-field"><span>Cấp bậc</span><select value={level} disabled={!exec} onChange={e => setLevel(e.target.value as MemberLevel)}>
        {(exec ? LEVELS : ['STAFF' as MemberLevel]).map(l => <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}</select></label>
      {level !== 'EXECUTIVE' && <label className="tv-field"><span>Phòng ban</span><DepartmentSelect space={space} value={dep} onChange={setDep} disabled={!exec} /></label>}
      <div className="ua-row"><button className="btn btn-dark" disabled={busy || !email.trim() || (level !== 'EXECUTIVE' && !dep)}><UserPlus size={15} />Gửi lời mời</button></div>
    </form>
    {live.length > 0 && <ul className="og-list og-compact">{live.map(i => <li key={i.invite_id}>
      <span className="og-li-main"><b>{i.kind === 'USER' ? i.invitee : i.kind === 'CODE' ? 'Mã mời' : 'Link mời'}</b>
        <small>{i.kind === 'USER' ? `${LEVEL_LABEL[i.level]}${i.department_id ? ` · ${depName[i.department_id] ?? ''}` : ''}` : `Đã dùng ${i.use_count}/${i.max_uses ?? '∞'}`}
          {i.expires_at ? ` · hết hạn ${new Date(i.expires_at).toLocaleDateString('vi-VN')}` : ''}</small></span>
      <span className="og-li-acts"><button className="btn btn-ghost is-sm" disabled={busy} onClick={() => onRevoke(i.invite_id)}>Thu hồi</button></span>
    </li>)}</ul>}
  </section>;
}

function DepartmentPanel({ space, exec, busy, onAdd, onDelete }: { space: OrgDetail; exec: boolean; busy: boolean; onAdd: (name: string) => void; onDelete: (id: string, name: string) => void }) {
  const [name, setName] = useState('');
  const count = (id: string) => space.members.filter(m => m.department_id === id && m.status === 'ACTIVE').length;
  return <section className="dz-card">
    <header><h3><Building2 size={16} />Phòng ban</h3></header>
    <div className="og-chips">{space.departments.map(d => <span key={d.department_id} className="og-chip"><b>{d.name}</b><small>{count(d.department_id)} người</small>
      {exec && <button disabled={busy} onClick={() => confirm(`Xóa phòng ${d.name}?`) && onDelete(d.department_id, d.name)} aria-label={`Xóa phòng ${d.name}`} title="Xóa phòng (phải không còn người, tài liệu)"><X size={13} /></button>}</span>)}
      {!space.departments.length && <span className="is-muted">Chưa có phòng ban.</span>}</div>
    {exec && <form className="ua-row og-addrow" onSubmit={e => { e.preventDefault(); onAdd(name.trim()); setName(''); }}>
      <input value={name} onChange={e => setName(e.target.value)} maxLength={120} placeholder="Tên phòng mới" aria-label="Tên phòng mới" />
      <button className="btn btn-ghost is-sm" disabled={busy || !name.trim()}><Plus size={14} />Thêm phòng</button></form>}
  </section>;
}

function DocumentPanel({ spaceId, space, docs, depName, busy, onChange, onShare }: {
  spaceId: string; space: OrgDetail; docs: DocumentInfo[]; depName: Record<string, string>; busy: boolean;
  onChange: (id: string, c: Classification) => void; onShare: (id: string, target: { user_id?: string; department_id?: string }) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const options = SETTABLE[space.me.level];
  return <section className="dz-card">
    <header><h3><ShieldCheck size={16} />Tài liệu và mức mật</h3></header>
    <p className="is-muted og-small">Tải tài liệu ở thanh bên (chọn mức mật trước khi tải). Người tải lên chỉ được tăng mức; hạ mức là việc của Trưởng phòng hoặc Ban giám đốc.</p>
    {!docs.length ? <p className="is-muted">Bạn chưa xem được tài liệu nào trong không gian này.</p> :
      <div className="tbl tv-table"><table><thead><tr><th>Tài liệu</th><th>Mức mật</th><th>Phòng</th><th>Người tải lên</th><th>Thao tác</th></tr></thead><tbody>
        {docs.map(d => { const id = String(d.id); const current = d.classification as Classification;
          return <React.Fragment key={id}><tr>
            <td><b>{d.source_file}</b></td>
            <td><select className={`og-class-select is-${current?.toLowerCase()}`} value={current} disabled={busy} aria-label={`Mức mật của ${d.source_file}`}
              onChange={e => onChange(id, e.target.value as Classification)}>
              {[...new Set([current, ...options])].map(c => <option key={c} value={c}>{CLASS_LABEL[c]}</option>)}</select></td>
            <td>{d.department_id ? depName[d.department_id] : <span className="is-muted">—</span>}</td>
            <td>{d.mine ? 'Bạn' : d.owner}{d.created_at && <small className="is-muted og-date">{new Date(d.created_at).toLocaleDateString('vi-VN')}</small>}</td>
            <td className="ua-acts"><button className="icon-btn is-sm" onClick={() => setOpen(open === id ? null : id)} aria-expanded={open === id} title="Chia sẻ" aria-label={`Chia sẻ ${d.source_file}`}><Share2 size={15} /></button></td>
          </tr>{open === id && <tr className="og-share-row"><td colSpan={5}><SharePanel spaceId={spaceId} sourceId={id} space={space} depName={depName} busy={busy} onShare={t => onShare(id, t)} /></td></tr>}</React.Fragment>; })}
      </tbody></table></div>}
  </section>;
}

function SharePanel({ spaceId, sourceId, space, depName, busy, onShare }: {
  spaceId: string; sourceId: string; space: OrgDetail; depName: Record<string, string>; busy: boolean; onShare: (t: { user_id?: string; department_id?: string }) => void;
}) {
  const [shares, setShares] = useState<OrgShare[]>([]);
  const [target, setTarget] = useState('');
  const [error, setError] = useState('');
  const load = () => listShares(spaceId, sourceId).then(setShares).catch(e => setError(e.message));
  useEffect(() => { void load(); }, [sourceId, busy]);
  const people = space.members.filter(m => m.status === 'ACTIVE');
  return <div className="og-share">
    <form className="og-inline" onSubmit={e => { e.preventDefault(); if (!target) return; const [kind, id] = target.split(':'); onShare(kind === 'd' ? { department_id: id } : { user_id: id }); setTarget(''); }}>
      <select value={target} onChange={e => setTarget(e.target.value)} aria-label="Chia sẻ cho">
        <option value="">Chọn người hoặc phòng</option>
        <optgroup label="Phòng ban">{space.departments.map(d => <option key={d.department_id} value={`d:${d.department_id}`}>{d.name}</option>)}</optgroup>
        <optgroup label="Thành viên">{people.map(m => <option key={m.user_id} value={`u:${m.user_id}`}>{m.display_name}</option>)}</optgroup>
      </select>
      <button className="btn btn-dark is-sm" disabled={busy || !target}><Share2 size={14} />Chia sẻ</button>
    </form>
    {error && <p className="note is-error">{error}</p>}
    {shares.length > 0 && <ul className="og-chips">{shares.map(s => <li key={s.share_id} className="og-chip"><b>{s.user ?? (s.department_id ? depName[s.department_id] : '')}</b><small>bởi {s.shared_by}</small>
      <button disabled={busy} onClick={() => unshare(spaceId, s.share_id).then(load).catch(e => setError(e.message))} aria-label="Gỡ chia sẻ" title="Gỡ chia sẻ"><X size={13} /></button></li>)}</ul>}
  </div>;
}
