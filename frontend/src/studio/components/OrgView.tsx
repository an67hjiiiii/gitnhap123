// Trang Tổ chức: tạo hoặc tham gia không gian tổ chức; khi đang mở một không gian thì quản lý thành viên, phòng ban,
// lời mời, yêu cầu chờ duyệt và mức mật / chia sẻ của tài liệu. Mọi quyền do backend quyết định (app/core/access.py);
// giao diện chỉ ẩn bớt nút người dùng chắc chắn không được bấm, lỗi 403 từ máy chủ vẫn được hiện nguyên văn.
import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, ArrowUpRight, Building2, Check, ChevronDown, ChevronRight, Copy, DoorOpen, FileText, KeyRound, LayoutGrid, Link2, LogIn, MoreHorizontal, Pencil, Plus, RefreshCw, Search, Settings, Share2, ShieldCheck, Sparkles, Trash2, UserCheck, UserPlus, Users, X } from 'lucide-react';
import {
  Classification, MemberLevel, MyInvite, ORG_PRESETS, OrgDetail, OrgInvite, OrgLabels, OrgPreset, OrgShare, OrgSpace, OrgTerms, SETTABLE, canChangeClass, classChoices, orgTerms, renameDepartment, updateSpace,
  answerInvite, approveMember, createDepartment, createJoinToken, deleteDepartment, getSpace, inviteByEmail, isOrgId, joinSpace,
  deleteSpace, leaveSpace, listInvites, listMySpaces, listShares, myInvites, removeMember, revokeInvite, shareSource, unshare, updateMember, updateSource,
} from '../services/api';
import { DocumentInfo } from '../types';
import { ToolHeader } from './analysis/shared';
import { Avatar } from './Avatar';
import { useDismiss } from './Header';
import { StudioModal } from './StudioModal';
import { LABEL_FIELDS, OrgWizard, PRESET_ICON, coverOf } from './OrgWizard';
import './profile/tools.css';
import '../styles/org.css';

const LEVELS: MemberLevel[] = ['STAFF', 'MANAGER', 'EXECUTIVE'];
const SCOPE_LIST: Classification[] = ['COMPANY', 'DEPARTMENT', 'RESTRICTED', 'SECRET', 'PRIVATE'];
// chế độ một đơn vị: mã đơn vị duy nhất, dùng thay cho ô chọn đơn vị
const onlyUnit = (space: OrgDetail) => space.departments.length === 1 ? space.departments[0].department_id : null;
const avatarHue = (id: string) => String([...id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7));
// chữ cái của từ cuối là chữ (bỏ qua phần như "(thử)"), theo cách gọi tên tiếng Việt
const initial = (name: string) => {
  const words = (name || '').trim().split(/\s+/).filter(w => /^\p{L}/u.test(w));
  return words.length ? words[words.length - 1][0].toUpperCase() : '?';
};
const presetOf = (p?: string | null) => ((p ?? '') in ORG_PRESETS ? p : 'business') as OrgPreset;
const SCOPE_COLOR: Record<Classification, string> = { COMPANY: '#7aa7ee', DEPARTMENT: '#a9c4f2', RESTRICTED: '#e9b98f', SECRET: '#d9958f', PRIVATE: '#c3cad6' };
const WEEKDAY = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];


function Donut({ parts, size = 136, stroke = 12 }: { parts: { v: number; c: string }[]; size?: number; stroke?: number }) {
  const r = (size - stroke) / 2, C = 2 * Math.PI * r, o = size / 2;
  const shown = parts.filter(p => p.v > 0), tot = shown.reduce((a, p) => a + p.v, 0), gap = shown.length > 1 ? 6 : 0;
  let off = 0;
  return <svg width={size} height={size} aria-hidden="true">
    <circle r={r} cx={o} cy={o} fill="none" style={{ stroke: 'var(--line)' }} strokeWidth={stroke} />
    {tot > 0 && shown.map((p, i) => { const L = C * p.v / tot; const el = <circle key={i} r={r} cx={o} cy={o} fill="none" stroke={p.c} strokeWidth={stroke}
      strokeLinecap="round" strokeDasharray={`${Math.max(L - gap, 1)} ${C}`} strokeDashoffset={-off - gap / 2} transform={`rotate(-90 ${o} ${o})`} />; off += L; return el; })}
  </svg>;
}

function Spark({ pts, w = 260, h = 84 }: { pts: number[]; w?: number; h?: number }) {
  const mx = Math.max(1, ...pts), step = w / (pts.length - 1);
  const d = 'M' + pts.map((p, i) => `${(i * step).toFixed(1)},${(h - 6 - (p / mx) * (h - 16)).toFixed(1)}`).join(' L');
  return <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none" aria-hidden="true">
    <defs><linearGradient id="og-sg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style={{ stopColor: 'var(--accent)', stopOpacity: .22 }} /><stop offset="1" style={{ stopColor: 'var(--accent)', stopOpacity: 0 }} /></linearGradient></defs>
    <path d={`${d} L${w},${h} L0,${h} Z`} fill="url(#og-sg)" />
    <path d={d} fill="none" style={{ stroke: 'var(--accent)' }} strokeWidth="1.8" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
  </svg>;
}

export function ClassBadge({ value, terms }: { value?: string | null; terms?: OrgTerms }) {
  if (!value) return null;
  const c = value as Classification;
  const t = terms ?? orgTerms();
  return <span className={`og-class is-${c.toLowerCase()}`} title={t.hint[c]}>{t.cls[c] ?? value}</span>;
}


// chọn loại hình tổ chức; "Tự đặt cách gọi" mở thêm 5 ô. Chỉ đổi chữ hiển thị, không đổi quyền.
function NamingFields({ preset, labels, onPreset, onLabels, disabled }: {
  preset: OrgPreset; labels: OrgLabels; onPreset: (p: OrgPreset) => void; onLabels: (l: OrgLabels) => void; disabled?: boolean;
}) {
  return <>
    <fieldset className="og-presets" disabled={disabled}>
      <legend>Loại hình tổ chức</legend>
      {(Object.keys(ORG_PRESETS) as OrgPreset[]).map(p => { const l = ORG_PRESETS[p].labels; const Icon = PRESET_ICON[p];
        return <label key={p} className={`og-preset${preset === p ? ' is-on' : ''}`}>
          <input type="radio" name="og-preset" value={p} checked={preset === p} onChange={() => {
            // sang "Tự đặt cách gọi" thì điền sẵn tên của loại hình đang chọn để chỉ sửa chỗ cần
            if (p === 'custom' && !Object.values(labels).some(v => v?.trim())) onLabels({ ...ORG_PRESETS[preset].labels });
            onPreset(p);
          }} />
          <span className="og-preset-ico" aria-hidden="true"><Icon size={18} /></span>
          <b>{ORG_PRESETS[p].name}</b>
          <small>{p === 'custom' ? 'Đặt tên các cấp theo ý bạn' : `${l.EXECUTIVE} › ${l.MANAGER} › ${l.STAFF}`}</small>
        </label>; })}
    </fieldset>
    {preset === 'custom' && <div className="og-naming">{LABEL_FIELDS.map(([k, label]) =>
      <label key={k} className="tv-field"><span>{label}</span><input maxLength={40} disabled={disabled} value={labels[k] ?? ''}
        placeholder={ORG_PRESETS.business.labels[k]} onChange={e => onLabels({ ...labels, [k]: e.target.value })} /></label>)}</div>}
  </>;
}

interface OrgViewProps {
  workspaceId: number | string;
  docs: DocumentInfo[];
  onOpenSpace: (id: string) => void;
  onChanged: () => Promise<void> | void;
  onAsk?: () => void;
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
  const [wizard, setWizard] = useState(false);
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
        <section className="og-home-hero">
          <div className="og-home-copy">
            <h1>Tổ chức của bạn</h1>
            <p>Không gian chung cho công ty, trường học, bệnh viện, cơ quan hay nhóm nhỏ. Mỗi người chỉ thấy và hỏi AI trên tài liệu mình được phép xem.</p>
            <form className="og-join" onSubmit={e => { e.preventDefault(); void run(async () => {
              const r = await joinSpace(token.trim()); setToken('');
              return `Đã gửi yêu cầu vào "${r.space_name}". Bạn vào được sau khi người quản lý của tổ chức duyệt.`;
            }); }}>
              <KeyRound size={16} aria-hidden="true" />
              <input value={token} onChange={e => setToken(e.target.value)} placeholder="Có mã mời? Nhập mã, ví dụ ABCD-EFGH" autoComplete="off" aria-label="Mã mời hoặc phần cuối của link" />
              <button className="btn btn-dark is-sm" disabled={busy || token.trim().length < 4}><LogIn size={14} />Tham gia</button>
            </form>
          </div>
          <div className="og-home-art" aria-hidden="true">
            <img className="is-a" src={coverOf('school')} alt="" />
            <img className="is-b" src={coverOf('business')} alt="" />
            <img className="is-c" src={coverOf('hospital')} alt="" />
          </div>
          <div className="og-home-acts">
            {onBack && <button className="btn btn-ghost is-sm" onClick={onBack}><ArrowLeft size={14} />Quay lại {spaces.find(s => s.space_id === currentId)?.name ?? 'tổ chức đang mở'}</button>}
            <button className="og-pill-dark" onClick={() => setWizard(true)}><Plus size={15} />Tạo tổ chức</button>
          </div>
        </section>
        {error && <p className="note is-error" role="alert">{error}</p>}
        {notice && <p className="note" role="status">{notice}</p>}

        {invites.length > 0 && <section className="dz-card og-invites">
          <header><h3><UserPlus size={16} />Lời mời đang chờ bạn <span className="og-count is-alert">{invites.length}</span></h3></header>
          <ul className="og-list">{invites.map(i => { const P = PRESET_ICON[((i.preset ?? '') in ORG_PRESETS ? i.preset : 'business') as OrgPreset];
            return <li key={i.invite_id}>
            <span className="og-org-ico" aria-hidden="true"><P size={18} /></span>
            <span className="og-li-main"><b>{i.space_name}</b><small>{i.inviter} mời bạn làm {orgTerms(i).level[i.level]}</small></span>
            <span className="og-li-acts">
              <button className="btn btn-dark is-sm" disabled={busy} onClick={() => run(async () => { const r = await answerInvite(i.invite_id, 'accept'); await onChanged(); onOpenSpace(r.space_id); })}><Check size={14} />Tham gia</button>
              <button className="btn btn-ghost is-sm" disabled={busy} onClick={() => run(async () => { await answerInvite(i.invite_id, 'decline'); return 'Đã từ chối lời mời.'; })}>Từ chối</button>
            </span></li>; })}</ul>
        </section>}

        {!spaces.length ? <section className="dz-card og-empty-hero">
          <span className="og-create-ico" aria-hidden="true"><Building2 size={24} /></span>
          <h3>Bạn chưa thuộc tổ chức nào</h3>
          <p className="is-muted">Tạo tổ chức cho đơn vị của bạn trong khoảng 30 giây, hoặc nhập mã mời bên dưới nếu đồng nghiệp đã mời bạn.</p>
          <div className="og-create-kinds" aria-hidden="true">{(['business', 'school', 'hospital', 'government', 'team'] as const).map(p => { const I = PRESET_ICON[p]; return <span key={p}><I size={15} /></span>; })}</div>
          <button className="btn btn-dark" onClick={() => setWizard(true)}><Plus size={15} />Tạo tổ chức đầu tiên</button>
        </section> : <>
        <h2 className="og-home-h">Tất cả tổ chức</h2>
        <section className="og-orgs" aria-label="Tổ chức của bạn">
          {spaces.map(s => { const kind = presetOf(s.preset); const P = PRESET_ICON[kind];
            const open = s.status === 'ACTIVE'; const on = s.space_id === currentId;
            const body = <>
              <span className="og-org-art" aria-hidden="true"><img src={coverOf(kind)} alt="" loading="lazy" />
                {on && <span className="og-org-now"><i />Đang mở</span>}
                {!open && <span className="og-org-now is-wait"><i />Chờ duyệt</span>}</span>
              <span className="og-org-main"><b>{s.name}</b><small><P size={13} aria-hidden="true" />{ORG_PRESETS[kind].name}</small></span>
              {open && typeof s.member_count === 'number' && <span className="og-org-stats">
                <span><b>{s.member_count}</b>thành viên</span>
                {(s.unit_count ?? 0) > 1 && <span><b>{s.unit_count}</b>{orgTerms(s).unit}</span>}
                {typeof s.doc_count === 'number' && <span><b>{s.doc_count}</b>tài liệu</span>}</span>}
              <span className="og-org-foot">
                {open && (s.members_preview?.length ?? 0) > 0 && <span className="og-org-people" aria-label="Thành viên">
                  {s.members_preview!.map(m => <Avatar key={m.user_id} value={m.avatar} className="ua-av og-av-sm" style={{ ['--h' as string]: avatarHue(m.user_id) }}>{initial(m.display_name)}</Avatar>)}
                  {(s.member_count ?? 0) > s.members_preview!.length && <span className="og-av-more">+{(s.member_count ?? 0) - s.members_preview!.length}</span>}</span>}
                <span className="og-org-role">{orgTerms(s).level[s.level]}{s.is_owner ? ' · Chủ' : ''}</span>
                {open && <span className="og-org-go"><ArrowUpRight size={15} /></span>}
              </span>
            </>;
            return open ? <button key={s.space_id} type="button" data-kind={kind} className={`og-org${on ? ' is-on' : ''}`} onClick={() => onOpenSpace(s.space_id)} aria-label={`Mở ${s.name}`}>{body}</button>
              : <div key={s.space_id} data-kind={kind} className="og-org is-pending" title="Đang chờ người quản lý duyệt">{body}</div>; })}
          {<button type="button" className="og-org is-add" onClick={() => setWizard(true)}>
            <span className="og-add-fan" aria-hidden="true">{(['business', 'school', 'hospital'] as const).map(k => <img key={k} src={coverOf(k)} alt="" loading="lazy" />)}</span>
            <span className="og-org-ico" aria-hidden="true"><Plus size={22} /></span>
            <span className="og-org-main"><b>Tạo tổ chức mới</b><small>Vài câu hỏi, khoảng 30 giây</small></span>
          </button>}
        </section></>}
      </div>
      {wizard && <OrgWizard onClose={() => setWizard(false)} onCreated={async () => { await onChanged(); await load(); }}
        onOpen={id => { setWizard(false); onOpenSpace(id); }} />}
    </main>
  );
}

type SpaceTab = 'overview' | 'members' | 'units' | 'docs' | 'settings';

// menu ⋯ ở đầu trang: thao tác hiếm dùng (đổi tổ chức, rời) không nằm ngang hàng nút chính
function MoreMenu({ items, small, label = 'Thêm thao tác' }: { items: { label: string; Icon: React.ElementType; onClick: () => void; danger?: boolean }[]; small?: boolean; label?: string }) {
  const [open, setOpen] = useState(false);
  const close = React.useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  return <div className="og-more" ref={ref}>
    <button className={small ? 'icon-btn is-sm' : 'btn og-more-btn btn-ghost'} aria-haspopup="menu" aria-expanded={open} aria-label={label} title={label} onClick={() => setOpen(v => !v)}><MoreHorizontal size={small ? 16 : 17} /></button>
    {open && <div className="og-more-menu" role="menu">{items.map(i => <button key={i.label} role="menuitem" className={i.danger ? 'is-danger' : ''}
      onClick={() => { setOpen(false); i.onClick(); }}><i.Icon size={15} />{i.label}</button>)}</div>}
  </div>;
}

// ---------------- Khi đang mở một không gian tổ chức
function SpaceManager({ spaceId, docs, onOpenSpace, onChanged, onAsk, onShowAll }: OrgViewProps & { spaceId: string; onShowAll: () => void }) {
  const [space, setSpace] = useState<OrgDetail | null>(null);
  const [invites, setInvites] = useState<OrgInvite[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [tab, setTab] = useState<SpaceTab>('overview');
  const [inviting, setInviting] = useState(false);
  const [q, setQ] = useState('');
  const [fLevel, setFLevel] = useState('');
  const [fUnit, setFUnit] = useState('');

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
  const t = orgTerms(space);
  const soleOwner = me.is_owner && ownerCount <= 1;

  const preset = ((space.preset ?? '') in ORG_PRESETS ? space.preset : 'business') as OrgPreset;
  const fold = (v: string) => v.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/gi, 'd').toLowerCase();
  const shownMembers = active.filter(m => (!fLevel || m.level === fLevel) && (!fUnit || m.department_id === fUnit)
    && (!q.trim() || fold(`${m.display_name} ${m.email ?? ''}`).includes(fold(q.trim()))));
  const canInvite = exec || manager;
  const leave = () => {
    if (soleOwner) {
      // chủ duy nhất rời thì không còn ai quản lý được tổ chức: chỉ đường thay vì để máy chủ từ chối
      setTab('settings'); setNotice('');
      setError(`Bạn là chủ duy nhất của ${space.name}. Muốn rời, hãy trao quyền chủ cho một thành viên ở cấp ${t.EXECUTIVE} (tab Thành viên), hoặc xóa ${t.org}.`);
      return;
    }
    if (!confirm(`Rời "${space.name}"? Bạn mất quyền xem tài liệu và hội thoại trong ${t.org} này ngay lập tức.`)) return;
    void run(async () => { const r = await leaveSpace(spaceId); await onChanged(); onOpenSpace(''); return r.drafts ? `Đã rời. ${r.drafts} bản nháp được bàn giao.` : `Đã rời ${t.org}.`; });
  };
  const tabs: { id: SpaceTab; label: string; Icon: React.ElementType; count?: number; alert?: boolean }[] = [
    { id: 'overview', label: 'Tổng quan', Icon: LayoutGrid },
    { id: 'members', label: 'Thành viên', Icon: Users, count: active.length, alert: canInvite && pending.length > 0 },
    ...(t.single ? [] : [{ id: 'units' as SpaceTab, label: t.Unit, Icon: Building2, count: space.departments.length }]),
    { id: 'docs', label: 'Tài liệu', Icon: FileText, count: docs.length },
    { id: 'settings', label: 'Cài đặt', Icon: Settings },
  ];
  // một đơn vị thì không có tab đơn vị: phần đơn vị nằm trong Cài đặt để vẫn thêm được đơn vị khi cần chia nhỏ
  const units = <DepartmentPanel space={space} docs={docs} exec={exec} busy={busy}
    onRename={(id, name) => run(async () => { await renameDepartment(spaceId, id, name); return `Đã đổi tên thành ${name}.`; }, true)}
    onAdd={name => run(async () => { await createDepartment(spaceId, name); return `Đã thêm ${t.unit} ${name}.`; }, true)}
    onDelete={(id, name) => run(async () => { await deleteDepartment(spaceId, id); return `Đã xóa ${t.unit} ${name}.`; }, true)} />;
  const pendingPanel = pending.length > 0 && canInvite && <section className="dz-card og-pending">
    <header><h3><UserCheck size={16} />Đang chờ duyệt <span className="og-count is-alert">{pending.length}</span></h3></header>
    <ul className="og-list">{pending.map(m => <PendingRow key={m.user_id} member={m} space={space} busy={busy}
      onApprove={(level, dep) => run(async () => { await approveMember(spaceId, m.user_id, level, dep); return `Đã duyệt ${m.display_name}.`; })}
      onReject={() => run(async () => { await removeMember(spaceId, m.user_id); return `Đã từ chối ${m.display_name}.`; })} />)}</ul>
  </section>;

  return (
    <main className="pg tl tone-overview og-page">
      <div className="pg-col tv-col">
        <section className="og-top">
          <p className="og-crumb"><button type="button" onClick={onShowAll}>Tổ chức</button><span aria-hidden="true">/</span><b>{space.name}</b></p>
          <nav className="og-seg" role="tablist" aria-label={`Quản lý ${t.org}`}>
            {tabs.map(x => <button key={x.id} role="tab" id={`og-tab-${x.id}`} aria-selected={tab === x.id} aria-controls="og-tabpanel"
              className={tab === x.id ? 'is-on' : ''} onClick={() => setTab(x.id)}>
              {x.label}{x.count !== undefined && <em>{x.count}</em>}{x.alert && <i className="og-dot" aria-label="Có yêu cầu chờ duyệt" />}
            </button>)}
          </nav>
          <div className="og-top-acts">
            {canInvite && <button className="og-pill-dark" disabled={busy} onClick={() => setInviting(true)}><UserPlus size={15} />Mời thành viên</button>}
            <MoreMenu items={[
              { label: 'Tất cả tổ chức', Icon: LayoutGrid, onClick: onShowAll },
              { label: `Rời ${t.org}`, Icon: DoorOpen, onClick: leave, danger: true },
            ]} />
          </div>
        </section>
        {/* kết quả thao tác hiện nổi ở góc màn hình: nút bấm có thể nằm cuối trang, xa phần đầu */}
        {(error || notice) && <div className={`st-toast is-${error ? 'error' : 'ok'}`} role={error ? 'alert' : 'status'}>
          <span>{error || notice}</span><button onClick={() => { setError(''); setNotice(''); }} aria-label="Đóng thông báo">×</button></div>}

        <div className="og-tabpanel" id="og-tabpanel" role="tabpanel" aria-labelledby={`og-tab-${tab}`} key={tab}>
          {tab === 'overview' && <Overview space={space} docs={docs} invites={invites} terms={t} preset={preset} depName={depName} busy={busy}
            canInvite={canInvite} onTab={setTab} onInvite={() => setInviting(true)} onAsk={onAsk}
            onApprove={(m, dep) => run(async () => { await approveMember(spaceId, m.user_id, 'STAFF', dep); return `Đã duyệt ${m.display_name}.`; })}
            onReject={m => run(async () => { await removeMember(spaceId, m.user_id); return `Đã từ chối ${m.display_name}.`; })} />}

          {tab === 'members' && <>
            {pendingPanel}
            <section className="dz-card">
              <header><h3><Users size={16} />Thành viên <span className="og-count">{active.length}</span></h3>
                <span className="og-inline">{canInvite && <button className="btn btn-ghost is-sm" onClick={() => setInviting(true)}><UserPlus size={14} />Mời</button>}
                  <button className="btn btn-ghost is-sm" onClick={() => void load()}><RefreshCw size={14} />Làm mới</button></span></header>
              <div className="og-toolbar">
                <label className="og-search"><Search size={15} /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm theo tên hoặc email" aria-label="Tìm thành viên" /></label>
                <select value={fLevel} onChange={e => setFLevel(e.target.value)} aria-label="Lọc theo cấp bậc">
                  <option value="">Mọi cấp bậc</option>{LEVELS.map(l => <option key={l} value={l}>{t.level[l]}</option>)}</select>
                {!t.single && <select value={fUnit} onChange={e => setFUnit(e.target.value)} aria-label={`Lọc theo ${t.unit}`}>
                  <option value="">Mọi {t.unit}</option>{space.departments.map(d => <option key={d.department_id} value={d.department_id}>{d.name}</option>)}</select>}
                {shownMembers.length !== active.length && <span className="og-toolbar-n">{shownMembers.length}/{active.length}</span>}
              </div>
              {!shownMembers.length ? <p className="og-empty">Không có thành viên khớp bộ lọc.</p> :
              <div className="tbl tv-table"><table><thead><tr><th>Thành viên</th>{!t.single && <th>{t.Unit}</th>}<th>Cấp bậc</th><th aria-label="Thao tác" /></tr></thead><tbody>
                {shownMembers.map(m => <MemberRow key={m.user_id} m={m} space={space} depName={depName} busy={busy} ownerCount={ownerCount}
                  onSave={body => run(async () => { await updateMember(spaceId, m.user_id, body); return `Đã cập nhật ${m.display_name}.`; })}
                  onRemove={() => {
                    if (!confirm(`Gỡ ${m.display_name} khỏi ${t.org}? Người này mất quyền ngay; bản nháp của họ được bàn giao cho ${t.MANAGER} hoặc ${t.EXECUTIVE}.`)) return;
                    void run(async () => { const r = await removeMember(spaceId, m.user_id); return r.drafts ? `Đã gỡ ${m.display_name}; bàn giao ${r.drafts} bản nháp.` : `Đã gỡ ${m.display_name}.`; });
                  }} />)}
              </tbody></table></div>}
            </section>
          </>}

          {tab === 'units' && units}

          {tab === 'docs' && <DocumentPanel spaceId={spaceId} space={space} docs={docs} depName={depName} busy={busy}
            onChange={(id, classification) => run(async () => { await updateSource(spaceId, id, { classification }); return `Đã đổi mức mật thành ${t.cls[classification]}.`; }, true)}
            onMove={(id, dep) => run(async () => { await updateSource(spaceId, id, { department_id: dep }); return `Đã chuyển tài liệu sang ${depName[dep] ?? t.unit}.`; }, true)}
            onShare={(id, target) => run(async () => { await shareSource(spaceId, id, target); return 'Đã chia sẻ. Người nhận được báo qua chuông thông báo.'; })} />}

          {tab === 'settings' && <>
            {exec && <NamingPanel space={space} busy={busy}
              onSave={body => run(async () => { await updateSpace(spaceId, body); await onChanged(); return 'Đã lưu cách gọi mới.'; })} />}
            {t.single && exec && units}
            <section className="dz-card og-row-card">
              <span className="og-danger-sum"><b>Rời {t.org}</b><small>{soleOwner ? `Bạn là chủ duy nhất: hãy trao quyền chủ cho người khác trước khi rời.` : `Bạn mất quyền xem tài liệu và hội thoại trong ${t.org} ngay lập tức.`}</small></span>
              <button className="btn btn-ghost is-sm" disabled={busy} onClick={leave}><DoorOpen size={14} />Rời {t.org}</button>
            </section>
            {me.is_owner && <DangerPanel space={space} members={active.length} busy={busy}
              onDelete={confirmName => run(async () => { await deleteSpace(spaceId, confirmName); await onChanged(); onOpenSpace(''); return `Đã xóa ${space.name}.`; })} />}
          </>}
        </div>
      </div>

      {/* gắn vào khung Studio: trang có lớp xếp chồng riêng nên thanh bên sẽ đè lên cửa sổ */}
      {inviting && createPortal(<StudioModal labelId="og-invite-title" title="Mời thành viên" subtitle={`Vào ${space.name}`} icon={<UserPlus size={18} />}
        size="md" onClose={() => { setInviting(false); setSecret(null); }}>
        {(error || notice) && <p className={`note${error ? ' is-error' : ''}`} role={error ? 'alert' : 'status'}>{error || notice}</p>}
        {secret && <section className="dz-card ua-secret" role="alert">
          <header><h3><KeyRound size={16} />{secret.label}</h3></header>
          <p className="is-muted">Chỉ hiện một lần. Gửi riêng cho người cần mời; người vào bằng mã hoặc link phải chờ duyệt.</p>
          <div className="ua-row"><code className="ua-pw og-secret">{secret.value}</code><CopyButton text={secret.value} /></div>
        </section>}
        <InvitePanel space={space} invites={invites} busy={busy} depName={depName}
          onEmail={(email, level, dep) => run(async () => { await inviteByEmail(spaceId, email, level, dep); return `Đã gửi lời mời tới ${email}. Họ sẽ thấy trong chuông thông báo.`; })}
          onToken={kind => run(async () => {
            const r = await createJoinToken(spaceId, kind);
            setSecret(kind === 'CODE' ? { label: 'Mã mời', value: r.token } : { label: 'Link mời', value: `${window.location.origin}/studio?join=${encodeURIComponent(r.token)}` });
          })}
          onRevoke={id => run(async () => { await revokeInvite(spaceId, id); return 'Đã thu hồi lời mời.'; })} />
      </StudioModal>, document.querySelector('.st-app') ?? document.body)}
    </main>
  );
}

// ---------------- Tab Tổng quan (mẫu E): thẻ tên có hình 3D, phạm vi tài liệu, tài liệu mới trong tuần, tài liệu gần đây, thành viên, việc cần làm.
// Mọi số đều đếm từ dữ liệu thật đang có trên trang (tài liệu bạn xem được, thành viên, lời mời); không có số ước tính.
type Member = OrgDetail['members'][number];
function Overview({ space, docs, invites, terms: t, preset, depName, busy, canInvite, onTab, onInvite, onAsk, onApprove, onReject }: {
  space: OrgDetail; docs: DocumentInfo[]; invites: OrgInvite[]; terms: OrgTerms; preset: OrgPreset; depName: Record<string, string>; busy: boolean;
  canInvite: boolean; onTab: (t: SpaceTab) => void; onInvite: () => void; onAsk?: () => void;
  onApprove: (m: Member, dep: string | null) => void; onReject: (m: Member) => void;
}) {
  const me = space.me;
  const active = space.members.filter(m => m.status === 'ACTIVE');
  const pending = space.members.filter(m => m.status === 'PENDING');
  const KindIcon = PRESET_ICON[preset];
  const scopes = SCOPE_LIST.filter(c => !(t.single && c === 'DEPARTMENT'))
    .map(c => ({ c, n: docs.filter(d => d.classification === c || (t.single && c === 'COMPANY' && d.classification === 'DEPARTMENT')).length }));
  // 7 ngày gần nhất theo giờ máy người xem
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const dayOf = (iso: string) => { const x = new Date(iso); x.setHours(0, 0, 0, 0); return x.getTime(); };
  const days = Array.from({ length: 7 }, (_, i) => new Date(today.getTime() - (6 - i) * 864e5));
  const week = days.map(d0 => docs.filter(d => d.created_at && dayOf(d.created_at) === d0.getTime()));
  const weekDocs = week.flat();
  const recent = [...docs].sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? ''))).slice(0, 5);
  const ago = (iso?: string) => { if (!iso) return ''; const n = Math.round((today.getTime() - dayOf(iso)) / 864e5);
    return n <= 0 ? 'Hôm nay' : n === 1 ? 'Hôm qua' : n < 7 ? `${n} ngày` : new Date(iso).toLocaleDateString('vi-VN'); };
  const perUnit = space.departments.map(d => ({ name: d.name, n: active.filter(m => m.department_id === d.department_id).length })).sort((a, b) => b.n - a.n).slice(0, 4);
  const maxUnit = Math.max(1, ...perUnit.map(u => u.n));
  const openInvites = invites.filter(i => !i.revoked);
  const only = onlyUnit(space);
  const unitFor = (m: Member) => only ?? m.department_id ?? (me.level === 'EXECUTIVE' ? null : me.department_id);
  return <div className="og-e">
    <article className="og-hero">
      <img className="og-hero-art" src={coverOf(preset)} alt="" />
      <span className="og-hero-tag"><KindIcon size={13} aria-hidden="true" />{ORG_PRESETS[preset].name} · {t.level[me.level]}{me.is_owner ? ', chủ tổ chức' : ''}</span>
      <h2>{space.name}</h2>
      <p>Mỗi người chỉ thấy và hỏi AI trên tài liệu mình được phép xem.</p>
      <div className="og-hero-kpis">
        <button type="button" onClick={() => onTab('members')}><b>{active.length}</b><span>thành viên</span></button>
        {!t.single && <button type="button" onClick={() => onTab('units')}><b>{space.departments.length}</b><span>{t.unit}</span></button>}
        <button type="button" onClick={() => onTab('docs')}><b>{docs.length}</b><span>tài liệu</span></button>
      </div>
    </article>

    <article className="og-e-card og-e-scope">
      <header><h3>Tài liệu theo phạm vi</h3></header>
      <div className="og-scope-wrap">
        <div className="og-ring"><Donut parts={scopes.map(s => ({ v: s.n, c: SCOPE_COLOR[s.c] }))} /><span><b>{docs.length}</b><small>tài liệu</small></span></div>
        <ul className="og-legend">{scopes.map(s => <li key={s.c} title={t.hint[s.c]}><i style={{ background: SCOPE_COLOR[s.c] }} />{t.cls[s.c]}<b>{s.n}</b></li>)}</ul>
      </div>
      <p className="og-e-note"><ShieldCheck size={14} aria-hidden="true" />AI chỉ đọc tài liệu người hỏi được xem.</p>
    </article>

    <article className="og-e-card og-e-week">
      <header><h3>Tài liệu mới trong tuần</h3></header>
      <p className="og-week-num"><b>{weekDocs.length}</b><span>trong 7 ngày qua</span></p>
      <Spark pts={week.map(w => w.length)} />
      <div className="og-week-days">{days.map(d => <span key={d.getTime()}>{WEEKDAY[d.getDay()]}</span>)}</div>
      <div className="og-mini">
        <div><b>{new Set(weekDocs.map(d => d.mine ? '__me' : d.owner)).size}</b><span>người tải lên</span></div>
        <div><b>{weekDocs.filter(d => d.mine).length}</b><span>do bạn tải lên</span></div>
      </div>
    </article>

    <article className="og-e-card og-e-docs">
      <header><h3>Tài liệu gần đây</h3>{docs.length > 0 && <button className="og-link" onClick={() => onTab('docs')}>Xem tất cả</button>}</header>
      {!recent.length ? <p className="og-empty">Chưa có tài liệu nào bạn xem được. Tải tài liệu ở thanh bên, chọn phạm vi trước khi tải.</p> : <>
        <div className="og-drow is-head"><span /><span>Tên</span><span>Phạm vi</span><span>Cập nhật</span></div>
        {recent.map(d => <div className="og-drow" key={String(d.id ?? d.source_file)}>
          <span className="og-dfile"><FileText size={14} /></span>
          <span className="og-dname"><b title={d.source_file}>{d.source_file}</b><small>{d.mine ? 'Bạn' : d.owner}{d.department_id && depName[d.department_id] && !t.single ? ` · ${depName[d.department_id]}` : ''}</small></span>
          <span><ClassBadge value={d.classification} terms={t} /></span>
          <span className="og-dwhen">{ago(d.created_at)}</span>
        </div>)}</>}
    </article>

    <article className="og-e-card og-e-mem">
      <header><h3>Thành viên</h3><button className="og-link" onClick={() => onTab('members')}>Xem tất cả</button></header>
      <ul className="og-people">{active.slice(0, 4).map(m => <li key={m.user_id}>
        <Avatar value={m.avatar} className="ua-av" style={{ ['--h' as string]: avatarHue(m.user_id) }}>{initial(m.display_name)}</Avatar>
        <span className="og-dname"><b>{m.display_name}</b><small>{m.department_id && !t.single ? depName[m.department_id] ?? '' : m.email ?? ''}</small></span>
        <span className="og-lv">{m.is_owner ? 'Chủ' : t.level[m.level]}</span></li>)}</ul>
      {!t.single && perUnit.length > 0 && <div className="og-bars"><p>Theo {t.unit}</p>
        {perUnit.map(u => <div key={u.name}><span>{u.name}</span><i><em style={{ width: `${(u.n / maxUnit) * 100}%` }} /></i><b>{u.n}</b></div>)}</div>}
    </article>

    <article className="og-e-card og-e-side">
      {canInvite ? <>
        <header><h3>Chờ duyệt {pending.length > 0 && <span className="og-count is-alert">{pending.length}</span>}</h3></header>
        {!pending.length ? <p className="og-empty">Không có ai đang chờ duyệt.</p> : <ul className="og-reqs">{pending.slice(0, 3).map(m => { const dep = unitFor(m);
          return <li key={m.user_id}>
            <Avatar value={m.avatar} className="ua-av" style={{ ['--h' as string]: avatarHue(m.user_id) }}>{initial(m.display_name)}</Avatar>
            <span className="og-dname"><b>{m.display_name}</b><small>{m.department_id && !t.single ? `Xin vào ${depName[m.department_id] ?? t.unit}` : m.email}</small></span>
            <button className="og-req-no" disabled={busy} onClick={() => onReject(m)} aria-label={`Từ chối ${m.display_name}`} title="Từ chối"><X size={13} /></button>
            {/* chưa rõ đơn vị thì chọn ở tab Thành viên */}
            <button className="og-req-yes" disabled={busy} onClick={() => dep ? onApprove(m, dep) : onTab('members')}
              aria-label={dep ? `Duyệt ${m.display_name} làm ${t.STAFF}` : `Chọn ${t.unit} cho ${m.display_name}`} title={dep ? `Duyệt làm ${t.STAFF}` : `Chọn ${t.unit} rồi duyệt`}><Check size={13} /></button>
          </li>; })}</ul>}
        <button type="button" className="og-code" onClick={onInvite}>
          <span><b>{openInvites.length ? `${openInvites.length} lời mời đang mở` : 'Chưa có lời mời nào'}</b><small>Mời qua email, mã hoặc link</small></span>
          <em><UserPlus size={14} />Mời</em>
        </button>
      </> : <>
        <header><h3>Ai xem được tài liệu nào</h3></header>
        <ul className="og-hints">{SCOPE_LIST.filter(c => !(t.single && c === 'DEPARTMENT')).map(c => <li key={c}><ClassBadge value={c} terms={t} /><span>{t.hint[c]}</span></li>)}</ul>
      </>}
      {onAsk && <button type="button" className="og-ask" onClick={onAsk}>
        <span className="og-ask-ico"><Sparkles size={17} /></span>
        <span><b>Hỏi AI trong {t.org}</b><small>Chỉ trên tài liệu bạn được xem</small></span>
        <ArrowUpRight size={15} className="og-ask-go" />
      </button>}
    </article>
  </div>;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return <button className="btn btn-ghost is-sm" onClick={async () => { await navigator.clipboard?.writeText(text).catch(() => undefined); setCopied(true); }}>
    {copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Đã chép' : 'Chép'}</button>;
}

function DepartmentSelect({ space, value, onChange, allowNone, disabled }: { space: OrgDetail; value: string | null; onChange: (v: string | null) => void; allowNone?: boolean; disabled?: boolean }) {
  return <select value={value ?? ''} disabled={disabled} onChange={e => onChange(e.target.value || null)} aria-label={orgTerms(space).Unit}>
    {allowNone && <option value="">Không thuộc {orgTerms(space).unit} nào</option>}
    {!allowNone && !value && <option value="">Chọn {orgTerms(space).unit}</option>}
    {space.departments.map(d => <option key={d.department_id} value={d.department_id}>{d.name}</option>)}
  </select>;
}

function PendingRow({ member, space, busy, onApprove, onReject }: {
  member: OrgDetail['members'][number]; space: OrgDetail; busy: boolean;
  onApprove: (level: MemberLevel, dep: string | null) => void; onReject: () => void;
}) {
  const exec = space.me.level === 'EXECUTIVE';
  const [level, setLevel] = useState<MemberLevel>('STAFF');
  const only = onlyUnit(space);
  const [dep, setDep] = useState<string | null>(member.department_id ?? (exec ? null : space.me.department_id));
  const unit = only ?? dep;  // chỉ một đơn vị thì luôn là đơn vị đó, kể cả khi số đơn vị vừa đổi
  const needDep = level !== 'EXECUTIVE' && !unit;
  return <li>
    <Avatar value={member.avatar} className="ua-av" style={{ ['--h' as string]: avatarHue(member.user_id) }}>{initial(member.display_name)}</Avatar>
    <span className="og-li-main"><b>{member.display_name}</b><small>{member.email}</small></span>
    <span className="og-li-acts og-inline">
      <select value={level} disabled={!exec} onChange={e => setLevel(e.target.value as MemberLevel)} aria-label="Cấp bậc khi duyệt">
        {(exec ? LEVELS : ['STAFF' as MemberLevel]).map(l => <option key={l} value={l}>{orgTerms(space).level[l]}</option>)}</select>
      {level !== 'EXECUTIVE' && !only && <DepartmentSelect space={space} value={dep} onChange={setDep} disabled={!exec} />}
      <button className="btn btn-dark is-sm" disabled={busy || needDep} onClick={() => onApprove(level, level === 'EXECUTIVE' ? null : unit)}><Check size={14} />Duyệt</button>
      <button className="btn btn-ghost is-sm" disabled={busy} onClick={onReject}><X size={14} />Từ chối</button>
    </span>
  </li>;
}

function MemberRow({ m, space, depName, busy, ownerCount, onSave, onRemove }: {
  m: OrgDetail['members'][number]; space: OrgDetail; depName: Record<string, string>; busy: boolean; ownerCount: number;
  onSave: (body: { level: MemberLevel; department_id: string | null; is_owner: boolean }) => void; onRemove: () => void;
}) {
  const me = space.me;
  const t = orgTerms(space);
  const exec = me.level === 'EXECUTIVE';
  const [editing, setEditing] = useState(false);
  const [level, setLevel] = useState<MemberLevel>(m.level);
  const [dep, setDep] = useState<string | null>(m.department_id);
  const [owner, setOwner] = useState(m.is_owner);
  const only = onlyUnit(space);
  const unit = level === 'EXECUTIVE' ? dep : dep ?? only;
  const canRemove = exec ? !(m.is_owner && (!me.is_owner || ownerCount <= 1))
    : me.level === 'MANAGER' && m.level === 'STAFF' && m.department_id === me.department_id;
  const actions = [
    ...(exec ? [{ label: `Đổi cấp bậc, ${t.unit}`, Icon: ShieldCheck, onClick: () => setEditing(true) }] : []),
    ...(canRemove ? [{ label: `Gỡ khỏi ${t.org}`, Icon: Trash2, onClick: onRemove, danger: true }] : []),
  ];
  return <tr className={editing ? 'is-editing' : ''}>
    <td><span className="ua-person"><Avatar value={m.avatar} className="ua-av" style={{ ['--h' as string]: avatarHue(m.user_id) }}>{initial(m.display_name)}</Avatar>
      <span><b>{m.display_name}</b><small className="is-muted">{m.email}</small></span></span></td>
    {!only && <td>{editing && level !== 'EXECUTIVE' ? <DepartmentSelect space={space} value={dep} onChange={setDep} /> : (m.department_id ? depName[m.department_id] : <span className="is-muted">—</span>)}</td>}
    <td>{editing
      ? <span className="og-inline"><select value={level} onChange={e => { const l = e.target.value as MemberLevel; setLevel(l); if (l !== 'EXECUTIVE') setOwner(false); }} aria-label="Cấp bậc">
          {LEVELS.map(l => <option key={l} value={l}>{t.level[l]}</option>)}</select>
          {me.is_owner && level === 'EXECUTIVE' && <label className="og-check"><input type="checkbox" checked={owner} onChange={e => setOwner(e.target.checked)} />Chủ</label>}</span>
      : <span className={`og-level is-${m.level.toLowerCase()}`}>{t.level[m.level]}{m.is_owner ? ' · Chủ' : ''}</span>}</td>
    <td className="ua-acts">{editing ? <>
        <button className="btn btn-dark is-sm" disabled={busy || (level !== 'EXECUTIVE' && !unit)} onClick={() => { onSave({ level, department_id: unit, is_owner: owner }); setEditing(false); }}><Check size={14} />Lưu</button>
        <button className="btn btn-ghost is-sm" onClick={() => { setEditing(false); setLevel(m.level); setDep(m.department_id); setOwner(m.is_owner); }}>Hủy</button></>
      : actions.length > 0 && <MoreMenu small items={actions} label={`Thao tác với ${m.display_name}`} />}</td>
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
  const unit = onlyUnit(space) ?? dep;
  const noUnit = level !== 'EXECUTIVE' && !space.departments.length;
  const live = invites.filter(i => !i.revoked);
  return <section className="dz-card">
    <header><h3><UserPlus size={16} />Mời bằng email</h3>
      <span className="og-inline"><button className="btn btn-ghost is-sm" disabled={busy} onClick={() => onToken('CODE')}><KeyRound size={14} />Tạo mã</button>
        <button className="btn btn-ghost is-sm" disabled={busy} onClick={() => onToken('LINK')}><Link2 size={14} />Tạo link</button></span></header>
    <form className="ua-grid og-invite" onSubmit={e => { e.preventDefault(); onEmail(email.trim(), level, level === 'EXECUTIVE' ? null : unit); setEmail(''); }}>
      <label className="tv-field"><span>Email tài khoản đã đăng ký</span><input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="dongnghiep@congty.vn" autoComplete="off" /></label>
      <label className="tv-field"><span>Cấp bậc</span><select value={level} disabled={!exec} onChange={e => setLevel(e.target.value as MemberLevel)}>
        {(exec ? LEVELS : ['STAFF' as MemberLevel]).map(l => <option key={l} value={l}>{orgTerms(space).level[l]}</option>)}</select></label>
      {level !== 'EXECUTIVE' && !onlyUnit(space) && <label className="tv-field"><span>{orgTerms(space).Unit}</span><DepartmentSelect space={space} value={dep} onChange={setDep} disabled={!exec} /></label>}
      {noUnit && <p className="is-muted og-small">Thêm ít nhất một {orgTerms(space).unit} ở phần bên dưới trước khi mời thành viên.</p>}
      <div className="ua-row"><button className="btn btn-dark" disabled={busy || !email.trim() || (level !== 'EXECUTIVE' && !unit)}><UserPlus size={15} />Gửi lời mời</button></div>
    </form>
    {live.length > 0 && <p className="og-sub">Lời mời đang hiệu lực ({live.length})</p>}
    {live.length > 0 && <ul className="og-list og-compact">{live.map(i => <li key={i.invite_id}>
      <span className="og-li-main"><b>{i.kind === 'USER' ? i.invitee : i.kind === 'CODE' ? 'Mã mời' : 'Link mời'}</b>
        <small>{i.kind === 'USER' ? `${orgTerms(space).level[i.level]}${i.department_id ? ` · ${depName[i.department_id] ?? ''}` : ''}` : `Đã dùng ${i.use_count}/${i.max_uses ?? '∞'}`}
          {i.expires_at ? ` · hết hạn ${new Date(i.expires_at).toLocaleDateString('vi-VN')}` : ''}</small></span>
      <span className="og-li-acts"><button className="btn btn-ghost is-sm" disabled={busy} onClick={() => onRevoke(i.invite_id)}>Thu hồi</button></span>
    </li>)}</ul>}
  </section>;
}

function DepartmentPanel({ space, docs, exec, busy, onAdd, onRename, onDelete }: {
  space: OrgDetail; docs: DocumentInfo[]; exec: boolean; busy: boolean; onAdd: (name: string) => void; onRename: (id: string, name: string) => void; onDelete: (id: string, name: string) => void;
}) {
  const [name, setName] = useState('');
  const t = orgTerms(space);
  const people = (id: string) => space.members.filter(m => m.department_id === id && m.status === 'ACTIVE');
  return <section className="dz-card">
    <header><h3><Building2 size={16} />{t.Unit} <span className="og-count">{space.departments.length}</span></h3></header>
    {t.single && <p className="is-muted og-small">Mọi thành viên đang thuộc chung một {t.unit}, nên không cần chọn {t.unit} khi mời người hay tải tài liệu. Khi cần chia nhỏ, hãy thêm {t.unit} mới; tài liệu đang để "{t.cls.COMPANY}" vẫn hiện với mọi người.</p>}
    <div className="og-units">
      {space.departments.map(d => { const ps = people(d.department_id); const heads = ps.filter(m => m.level === 'MANAGER');
        // chỉ đếm tài liệu thuộc riêng đơn vị (Nội bộ, Hạn chế); tài liệu toàn tổ chức có thể còn ghi đơn vị cũ
        const nDocs = docs.filter(x => x.department_id === d.department_id && (x.classification === 'DEPARTMENT' || x.classification === 'RESTRICTED')).length;
        return <article key={d.department_id} className="og-unit">
          <header><span className="og-unit-ico"><Building2 size={16} /></span><b>{d.name}</b>
            {exec && <MoreMenu small label={`Thao tác với ${d.name}`} items={[
              { label: 'Đổi tên', Icon: Pencil, onClick: () => { const v = prompt(`Tên mới cho ${t.unit} "${d.name}"`, d.name)?.trim(); if (v && v !== d.name) onRename(d.department_id, v); } },
              { label: `Xóa ${t.unit}`, Icon: Trash2, danger: true, onClick: () => {
                if (ps.length || nDocs) { alert(`${t.Unit} ${d.name} còn ${ps.length} người và ${nDocs} tài liệu riêng. Chuyển sang ${t.unit} khác trước khi xóa.`); return; }
                if (confirm(`Xóa ${t.unit} ${d.name}?`)) onDelete(d.department_id, d.name);
              } },
            ]} />}</header>
          <p className="og-unit-stats"><span><Users size={13} />{ps.length} người</span><span><FileText size={13} />{nDocs} tài liệu</span></p>
          <p className="og-unit-head">{heads.length ? `${t.MANAGER}: ${heads.map(h => h.display_name).join(', ')}` : `Chưa có ${t.MANAGER.toLowerCase()}`}</p>
        </article>; })}
      {exec && <form className="og-unit is-add" onSubmit={e => { e.preventDefault(); if (name.trim()) { onAdd(name.trim()); setName(''); } }}>
        <span className="og-unit-ico"><Plus size={16} /></span>
        <input value={name} onChange={e => setName(e.target.value)} maxLength={120} placeholder={`Tên ${t.unit} mới`} aria-label={`Tên ${t.unit} mới`} />
        <button className="btn btn-ghost is-sm" disabled={busy || !name.trim()}>Thêm</button>
      </form>}
      {!space.departments.length && !exec && <p className="og-empty">Chưa có {t.unit} nào.</p>}
    </div>
  </section>;
}

function DocumentPanel({ spaceId, space, docs, depName, busy, onChange, onMove, onShare }: {
  spaceId: string; space: OrgDetail; docs: DocumentInfo[]; depName: Record<string, string>; busy: boolean;
  onChange: (id: string, c: Classification) => void; onMove: (id: string, dep: string) => void; onShare: (id: string, target: { user_id?: string; department_id?: string }) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [f, setF] = useState<Classification | ''>('');
  const options = SETTABLE[space.me.level];
  const t = orgTerms(space);
  const exec = space.me.level === 'EXECUTIVE';
  const levels = SCOPE_LIST.filter(c => docs.some(d => d.classification === c));
  const shown = docs.filter(d => (!f || d.classification === f) && (!q.trim() || d.source_file.toLowerCase().includes(q.trim().toLowerCase())));
  return <section className="dz-card">
    <header><h3><FileText size={16} />Tài liệu <span className="og-count">{docs.length}</span></h3></header>
    <p className="is-muted og-small">Tải tài liệu ở thanh bên. Người tải lên chỉ được nâng mức; hạ mức do {t.MANAGER} hoặc {t.EXECUTIVE} làm.</p>
    {!docs.length ? <p className="og-empty">Bạn chưa xem được tài liệu nào trong {t.org} này.</p> : <>
      <div className="og-toolbar">
        <label className="og-search"><Search size={15} /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm theo tên tài liệu" aria-label="Tìm tài liệu" /></label>
        <div className="og-filter" role="group" aria-label="Lọc theo mức mật">
          <button type="button" className={!f ? 'is-on' : ''} onClick={() => setF('')}>Tất cả <span>{docs.length}</span></button>
          {levels.map(c => <button key={c} type="button" className={f === c ? 'is-on' : ''} onClick={() => setF(f === c ? '' : c)}>
            {t.cls[c]} <span>{docs.filter(d => d.classification === c).length}</span></button>)}
        </div>
      </div>
      {!shown.length ? <p className="og-empty">Không có tài liệu khớp bộ lọc.</p> :
      <div className="tbl tv-table"><table><thead><tr><th>Tài liệu</th><th>Mức mật</th>{!t.single && <th>{t.Unit}</th>}<th>Người tải lên</th><th aria-label="Thao tác" /></tr></thead><tbody>
        {shown.map(d => { const id = String(d.id); const current = d.classification as Classification;
          const doc = { mine: !!d.mine, department_id: d.department_id ?? null, current };
          const choices = classChoices(t, options, current).filter(c => canChangeClass(space.me, doc, c, onlyUnit(space)));
          const bound = current === 'DEPARTMENT' || current === 'RESTRICTED';
          return <React.Fragment key={id}><tr>
            <td><span className="og-doc"><FileText size={15} /><b>{d.source_file}</b></span></td>
            <td>{choices.length < 2 ? <ClassBadge value={current} terms={t} />
              : <span className={`og-class-pick is-${current.toLowerCase()}`}>
                  <select className={`og-class-select is-${current.toLowerCase()}`} value={current} disabled={busy} aria-label={`Đổi mức mật của ${d.source_file}`}
                    onChange={e => onChange(id, e.target.value as Classification)}>
                    {choices.map(c => <option key={c} value={c}>{t.cls[c]}</option>)}</select><ChevronDown size={13} aria-hidden="true" /></span>}</td>
            {!t.single && <td>{!bound ? <span className="is-muted" title={`Mức này không gắn với ${t.unit} nào`}>—</span>
              : exec ? <select className="og-unit-select" value={d.department_id ?? ''} disabled={busy} aria-label={`${t.Unit} của ${d.source_file}`} onChange={e => e.target.value && onMove(id, e.target.value)}>
                  {space.departments.map(x => <option key={x.department_id} value={x.department_id}>{x.name}</option>)}</select>
              : d.department_id ? depName[d.department_id] : <span className="is-muted">—</span>}</td>}
            <td><span className="og-owner">{d.mine ? 'Bạn' : d.owner}{d.created_at && <small>{new Date(d.created_at).toLocaleDateString('vi-VN')}</small>}</span></td>
            <td className="ua-acts"><button className={`btn btn-ghost is-sm${open === id ? ' is-on' : ''}`} onClick={() => setOpen(open === id ? null : id)} aria-expanded={open === id} aria-label={`Chia sẻ ${d.source_file}`}><Share2 size={14} />Chia sẻ</button></td>
          </tr>{open === id && <tr className="og-share-row"><td colSpan={t.single ? 4 : 5}><SharePanel spaceId={spaceId} sourceId={id} space={space} depName={depName} busy={busy} onShare={t => onShare(id, t)} /></td></tr>}</React.Fragment>; })}
      </tbody></table></div>}
    </>}
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
        <option value="">{onlyUnit(space) ? 'Chọn người' : `Chọn người hoặc ${orgTerms(space).unit}`}</option>
        {!onlyUnit(space) && <optgroup label={orgTerms(space).Unit}>{space.departments.map(d => <option key={d.department_id} value={`d:${d.department_id}`}>{d.name}</option>)}</optgroup>}
        <optgroup label="Thành viên">{people.map(m => <option key={m.user_id} value={`u:${m.user_id}`}>{m.display_name}</option>)}</optgroup>
      </select>
      <button className="btn btn-dark is-sm" disabled={busy || !target}><Share2 size={14} />Chia sẻ</button>
    </form>
    {error && <p className="note is-error">{error}</p>}
    {shares.length > 0 && <ul className="og-chips">{shares.map(s => <li key={s.share_id} className="og-chip"><b>{s.user ?? (s.department_id ? depName[s.department_id] : '')}</b><small>bởi {s.shared_by}</small>
      <button disabled={busy} onClick={() => unshare(spaceId, s.share_id).then(load).catch(e => setError(e.message))} aria-label="Gỡ chia sẻ" title="Gỡ chia sẻ"><X size={13} /></button></li>)}</ul>}
  </div>;
}

// Cấp cao nhất đổi loại hình / cách gọi sau khi đã tạo; không gian cũ mặc định là Doanh nghiệp.
function NamingPanel({ space, busy, onSave }: { space: OrgDetail; busy: boolean; onSave: (body: { preset: OrgPreset; labels: OrgLabels | null }) => void }) {
  const start = (space.preset ?? '') in ORG_PRESETS ? space.preset as OrgPreset : 'business';
  const [preset, setPreset] = useState<OrgPreset>(start);
  const [labels, setLabels] = useState<OrgLabels>(space.labels ?? {});
  const t = orgTerms({ preset, labels: preset === 'custom' ? labels : null, departments: space.departments });
  return <section className="dz-card">
    <header><h3><LayoutGrid size={16} />Loại hình và cách gọi</h3></header>
    <form onSubmit={e => { e.preventDefault(); onSave({ preset, labels: preset === 'custom' ? labels : null }); }}>
      <NamingFields preset={preset} labels={labels} onPreset={setPreset} onLabels={setLabels} disabled={busy} />
      <p className="is-muted og-small">Các cấp: {t.EXECUTIVE} · {t.MANAGER} · {t.STAFF}. Phạm vi tài liệu: "{t.cls.COMPANY}"{t.single ? '' : `, "${t.cls.DEPARTMENT}"`}. Đổi cách gọi không làm thay đổi quyền xem tài liệu của ai.</p>
      <div className="ua-row"><button className="btn btn-dark is-sm" disabled={busy}><Check size={14} />Lưu</button></div>
    </form>
  </section>;
}

// Chỉ chủ thấy. Gõ lại đúng tên mới bấm được; máy chủ kiểm tra lại tên và quyền chủ.
function DangerPanel({ space, members, busy, onDelete }: { space: OrgDetail; members: number; busy: boolean; onDelete: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const t = orgTerms(space);
  const ok = name.trim() === space.name.trim();
  const others = members - 1;
  // thu gọn mặc định: chỉ mở phần cảnh báo và ô xác nhận khi người dùng thật sự bấm xóa
  if (!open) return <section className="dz-card og-danger is-closed" id="og-danger">
    <span className="og-danger-sum"><b>Xóa {t.org}</b><small>Xóa vĩnh viễn {t.org} và toàn bộ tài liệu.</small></span>
    <button className="btn btn-ghost is-sm og-danger-open" onClick={() => setOpen(true)}><Trash2 size={14} />Xóa {t.org}</button>
  </section>;
  return <section className="dz-card og-danger" id="og-danger">
    <header><h3><Trash2 size={16} />Xóa {t.org}</h3>
      <button className="btn btn-ghost is-sm" onClick={() => { setOpen(false); setName(''); }}>Hủy</button></header>
    <ul className="og-danger-list">
      <li>{others > 0 ? `${others} thành viên khác mất quyền truy cập ngay và nhận thông báo.` : `Chỉ có bạn trong ${t.org}, không ai khác bị ảnh hưởng.`}</li>
      <li>Toàn bộ tài liệu của {t.org} bị xóa, kể cả bản trong kho tìm kiếm của AI. Không khôi phục được.</li>
      <li>Lời mời, mã mời và các {t.unit} bị hủy. Lịch sử hỏi đáp được giữ lại để lưu trữ nhưng không ai mở được.</li>
    </ul>
    <form className="og-danger-form" onSubmit={e => { e.preventDefault(); if (ok) onDelete(name); }}>
      <label className="tv-field"><span>Gõ lại <b>{space.name}</b> để xác nhận</span>
        <input autoFocus value={name} onChange={e => setName(e.target.value)} autoComplete="off" placeholder={space.name} /></label>
      <button className="btn og-danger-btn" disabled={busy || !ok}><Trash2 size={15} />Xóa vĩnh viễn {t.org}</button>
    </form>
  </section>;
}
