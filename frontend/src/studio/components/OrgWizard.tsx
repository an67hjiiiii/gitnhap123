// Luồng tạo tổ chức từng bước: mỗi màn hỏi một câu, Robot C27 dẫn dắt, sơ đồ tổ chức xem trước cập nhật trực tiếp.
// Chỉ gọi các API sẵn có (tạo tổ chức, mời, tạo mã); mọi quyền vẫn do backend quyết định (app/core/access.py).
import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, ArrowRight, Building2, Check, Copy, GraduationCap, KeyRound, Landmark, Mail, PartyPopper, PenLine, Plus, Sparkles, Stethoscope, Users, X } from 'lucide-react';
import { MemberLevel, ORG_PRESETS, OrgLabels, OrgPreset, createJoinToken, createSpace, getSpace, inviteByEmail, orgTerms } from '../services/api';
import { StudioModal } from './StudioModal';
import { AssistantRobot } from './robot/AssistantRobot';
import type { RobotState } from './robot/robotEngine';

export const PRESET_ICON: Record<OrgPreset, React.ElementType> = { business: Building2, school: GraduationCap, hospital: Stethoscope, government: Landmark, team: Users, custom: PenLine };
export const LABEL_FIELDS: [keyof OrgLabels, string][] = [
  ['org', 'Cả tổ chức gọi là'], ['unit', 'Mỗi đơn vị gọi là'], ['EXECUTIVE', 'Cấp cao nhất'], ['MANAGER', 'Người phụ trách đơn vị'], ['STAFF', 'Thành viên'],
];
// hình 3D Icons8 cho từng loại; cơ quan và "tự đặt" dùng chung phòng họp
const COVER: Record<OrgPreset, string> = { business: 'business', government: 'business', custom: 'business', school: 'school', hospital: 'hospital', team: 'team' };
export const coverOf = (p: OrgPreset) => `${import.meta.env.BASE_URL}org-covers/${COVER[p]}.webp`;
const EXAMPLE_NAME: Record<OrgPreset, string> = {
  business: 'Công ty Minh Long', school: 'Trường Đại học Duy Tân', hospital: 'Bệnh viện Đa khoa Hòa Bình',
  government: 'Sở Thông tin và Truyền thông', team: 'CLB Lập trình', custom: 'Viện Nghiên cứu X',
};
const UNIT_IDEAS: Record<OrgPreset, string[]> = {
  business: ['Kinh doanh', 'Kế toán', 'Nhân sự', 'Kỹ thuật', 'Marketing'],
  school: ['Công nghệ thông tin', 'Kinh tế', 'Ngoại ngữ', 'Y dược', 'Luật'],
  hospital: ['Nội', 'Ngoại', 'Nhi', 'Sản', 'Cấp cứu'],
  government: ['Văn phòng', 'Tổ chức cán bộ', 'Kế hoạch tài chính', 'Thanh tra'],
  team: ['Kỹ thuật', 'Truyền thông', 'Sự kiện', 'Hậu cần'],
  custom: ['Nhóm A', 'Nhóm B'],
};
const STEPS = ['Loại hình', 'Tên', 'Đơn vị', 'Mời người', 'Xem lại'];
const DRAFT_KEY = 'c27-org-wizard-draft';
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface Invitee { email: string; level: MemberLevel; unit: string | null }
interface Draft { step: number; preset: OrgPreset | null; labels: OrgLabels; name: string; split: boolean | null; units: string[]; invitees: Invitee[]; wantCode: boolean }
const EMPTY: Draft = { step: 0, preset: null, labels: {}, name: '', split: null, units: [], invitees: [], wantCode: false };
interface Result { spaceId: string; name: string; failed: { email: string; reason: string }[]; code: string | null }

function loadDraft(): Draft {
  try { const d = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); return d && typeof d === 'object' ? { ...EMPTY, ...d } : EMPTY; } catch { return EMPTY; }
}

export function OrgWizard({ onClose, onCreated, onOpen }: { onClose: () => void; onCreated: () => Promise<void> | void; onOpen: (spaceId: string) => void }) {
  const [d, setD] = useState<Draft>(loadDraft);
  // mở lại khi còn bản nháp: báo rõ và cho bắt đầu lại, tránh tên, đơn vị cũ lẫn vào tổ chức mới
  const [resumed, setResumed] = useState(() => { const x = loadDraft(); return x.preset !== null || !!x.name.trim() || x.units.length > 0; });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [unitText, setUnitText] = useState('');
  const [emailText, setEmailText] = useState('');
  const [talking, setTalking] = useState(true);
  const set = (patch: Partial<Draft>) => setD(prev => ({ ...prev, ...patch }));
  const preset = d.preset ?? 'business';
  const t = orgTerms({ preset, labels: preset === 'custom' ? d.labels : null, unit_count: d.split ? Math.max(d.units.length, 1) : 1 });
  const units = d.split ? d.units : [];
  const step = result ? 5 : d.step;

  // lưu nháp để đóng giữa chừng không mất; xóa khi đã tạo xong
  useEffect(() => { try { result ? localStorage.removeItem(DRAFT_KEY) : localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch { /* trình duyệt chặn bộ nhớ: bỏ qua */ } }, [d, result]);
  useEffect(() => { setTalking(true); const h = window.setTimeout(() => setTalking(false), 1800); return () => window.clearTimeout(h); }, [step]);

  const canNext = [
    d.preset !== null,
    d.name.trim().length > 0,
    d.split === false || (d.split === true && d.units.length > 0),
    true,
    true,
  ][d.step];
  const [back, setBack] = useState(false);  // quay lại thì bước mới trượt vào từ bên trái
  const go = (n: number) => { setError(''); setBack(n < d.step); set({ step: Math.max(0, Math.min(4, n)) }); };
  const next = () => { if (canNext) go(d.step + 1); };

  const say = result ? `Xong rồi! ${result.name} đã sẵn sàng. Vào ngay để tải tài liệu đầu tiên nhé.`
    : busy ? 'Đang tạo, chờ mình một chút…'
    : [
      'Chào bạn! Mình sẽ giúp bạn tạo tổ chức trong vài bước. Tổ chức của bạn thuộc loại nào?',
      `Tuyệt! ${t.org.charAt(0).toUpperCase() + t.org.slice(1)} của bạn tên là gì?`,
      d.split && d.units.length ? `Đã có ${d.units.length} ${t.unit}. Thêm nữa hoặc sang bước tiếp nhé.` : `${d.name.trim() || 'Tổ chức'} có chia thành các ${t.unit} không?`,
      d.invitees.length ? `Sẽ mời ${d.invitees.length} người. Bạn chỉnh cấp bậc cho từng người ở bên dưới.` : 'Mời đồng nghiệp ngay bây giờ, hoặc bỏ qua và mời sau cũng được.',
      'Xem lại một chút trước khi tạo nhé. Bấm "Sửa" để quay lại bước bất kỳ.',
    ][d.step];
  const robotState: RobotState = result ? 'happy' : busy ? 'thinking' : talking ? 'speaking' : 'idle';

  const addUnits = (raw: string) => {
    const fresh = raw.split(/[,;\n]/).map(s => s.trim().slice(0, 120)).filter(Boolean);
    const all = [...d.units];
    for (const u of fresh) if (!all.some(x => x.toLowerCase() === u.toLowerCase()) && all.length < 50) all.push(u);
    set({ units: all, split: true });
  };
  const removeUnit = (u: string) => set({ units: d.units.filter(x => x !== u), invitees: d.invitees.map(i => i.unit === u ? { ...i, unit: null } : i) });
  const addEmails = (raw: string) => {
    const found = raw.split(/[\s,;]+/).map(s => s.trim().toLowerCase()).filter(Boolean);
    const bad = found.filter(e => !EMAIL.test(e));
    const list = [...d.invitees];
    for (const email of found) if (EMAIL.test(email) && !list.some(i => i.email === email)) list.push({ email, level: 'STAFF', unit: units[0] ?? null });
    set({ invitees: list });
    setEmailText(bad.join(' '));
    setError(bad.length ? `Email chưa đúng: ${bad.join(', ')}` : '');
  };
  const editInvitee = (email: string, patch: Partial<Invitee>) => set({ invitees: d.invitees.map(i => i.email === email ? { ...i, ...patch } : i) });

  const create = async () => {
    setBusy(true); setError('');
    try {
      const unitNames = units.length ? units : [`${t.Unit} chung`];
      const r = await createSpace(d.name.trim(), unitNames, preset, preset === 'custom' ? d.labels : null);
      // tổ chức đã có; từ đây lỗi mời từng người chỉ được báo lại, không làm hỏng việc tạo
      const detail = await getSpace(r.space_id);
      const idOf = Object.fromEntries(detail.departments.map(x => [x.name, x.department_id]));
      const failed: Result['failed'] = [];
      for (const i of d.invitees) {
        const dep = i.level === 'EXECUTIVE' ? null : idOf[i.unit ?? unitNames[0]] ?? detail.departments[0]?.department_id ?? null;
        try { await inviteByEmail(r.space_id, i.email, i.level, dep); } catch (e: any) { failed.push({ email: i.email, reason: e.message }); }
      }
      let code: string | null = null;
      if (d.wantCode) code = await createJoinToken(r.space_id, 'CODE').then(x => x.token).catch(() => null);
      await onCreated();
      setResult({ spaceId: r.space_id, name: r.name, failed, code });
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  // phím tắt: 1–6 chọn loại hình ở bước đầu
  useEffect(() => {
    if (step !== 0) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return;
      const p = (Object.keys(ORG_PRESETS) as OrgPreset[])[Number(e.key) - 1];
      if (p) pickPreset(p);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
  const pickPreset = (p: OrgPreset) => {
    if (p === 'custom') { set({ preset: p, labels: Object.values(d.labels).some(v => v?.trim()) ? d.labels : { ...ORG_PRESETS[d.preset ?? 'business'].labels } }); return; }
    set({ preset: p, step: 1 });  // chọn xong tự sang bước sau
  };

  const footer = result ? null : <>
    {d.step > 0 && <button className="btn btn-ghost" disabled={busy} onClick={() => go(d.step - 1)}><ArrowLeft size={15} />Quay lại</button>}
    <span className="ow-foot-gap" />
    {d.step === 3 && !d.invitees.length && !d.wantCode && <button className="btn btn-ghost" onClick={next}>Bỏ qua</button>}
    {d.step < 4
      ? <button className="btn btn-dark" disabled={!canNext} onClick={next}>Tiếp<ArrowRight size={15} /></button>
      : <button className="btn btn-dark ow-create" disabled={busy || !d.name.trim()} onClick={() => void create()}><Sparkles size={15} />{busy ? 'Đang tạo…' : `Tạo ${t.org}`}</button>}
  </>;

  // gắn thẳng vào khung Studio (giữ biến màu, giao diện tối): trang Tổ chức có lớp xếp chồng riêng nên thanh bên sẽ đè lên cửa sổ
  return createPortal(
    <StudioModal labelId="ow-title" title="Tạo tổ chức mới" onClose={onClose} footer={footer}
      icon={<Building2 size={18} />}
      subtitle={!result && <span className="ow-progress" aria-label={`Bước ${d.step + 1} trên ${STEPS.length}`}>
        {STEPS.map((s, i) => <i key={s} className={i < d.step ? 'is-done' : i === d.step ? 'is-on' : ''} title={s} />)}
        <em>Bước {d.step + 1}/{STEPS.length} · {STEPS[d.step]}</em></span>}>
      <div className={`ow${result ? ' is-done' : ''}`}>
        <div className="ow-main">
          <div className="ow-robot">
            <span className="ow-bot"><AssistantRobot size={64} interactive={false} state={robotState} colorConfig={{ shell: '#1d344a', trim: '#d5dde6', screen: '#8fdcff' }} /></span>
            <p className="ow-bubble" aria-live="polite" key={say}>{say}</p>
          </div>

          {resumed && !result && <p className="ow-resume"><span>Đang tiếp tục phần bạn nhập lần trước{d.name.trim() ? ` (${d.name.trim()})` : ''}.</span>
            <button type="button" className="btn btn-ghost is-sm" onClick={() => { setD(EMPTY); setUnitText(''); setEmailText(''); setError(''); setResumed(false); }}>Bắt đầu lại</button></p>}
          <div className={`ow-step${back ? ' is-back' : ''}`} key={step}>
            {step === 0 && <>
              <div className="ow-cards" role="radiogroup" aria-label="Loại hình tổ chức">
                {(Object.keys(ORG_PRESETS) as OrgPreset[]).map((p, i) => { const Icon = PRESET_ICON[p]; const l = ORG_PRESETS[p].labels;
                  return <button key={p} type="button" role="radio" aria-checked={d.preset === p} className={`ow-card is-art${d.preset === p ? ' is-on' : ''}`}
                    onClick={() => pickPreset(p)} data-autofocus={i === 0 ? true : undefined}>
                    <span className="ow-card-art"><img src={coverOf(p)} alt="" loading="lazy" /></span>
                    {d.preset === p && <span className="ow-card-check" aria-hidden="true"><Check size={13} /></span>}
                    <b><Icon size={15} aria-hidden="true" />{ORG_PRESETS[p].name}</b>
                    <small>{p === 'custom' ? 'Tự đặt tên các cấp' : `${l.EXECUTIVE} › ${l.MANAGER} › ${l.STAFF}`}</small>
                    <kbd>{i + 1}</kbd>
                  </button>; })}
              </div>
              {d.preset === 'custom' && <div className="ow-custom">
                {LABEL_FIELDS.map(([k, label]) => <label key={k} className="tv-field"><span>{label}</span>
                  <input maxLength={40} value={d.labels[k] ?? ''} placeholder={ORG_PRESETS.business.labels[k]} onChange={e => set({ labels: { ...d.labels, [k]: e.target.value } })} /></label>)}
              </div>}
            </>}

            {step === 1 && <form className="ow-ask" onSubmit={e => { e.preventDefault(); next(); }}>
              <input className="ow-big" autoFocus maxLength={120} value={d.name} onChange={e => set({ name: e.target.value })}
                placeholder={`VD: ${EXAMPLE_NAME[preset]}`} aria-label={`Tên ${t.org}`} />
              <p className="ow-hint">Nhấn <kbd>Enter</kbd> để tiếp tục. Bạn sẽ là chủ {t.org}, ở cấp {t.EXECUTIVE}.</p>
            </form>}

            {step === 2 && <>
              <div className="ow-choice">
                <button type="button" className={`ow-card is-wide${d.split === false ? ' is-on' : ''}`} onClick={() => set({ split: false, step: 3 })}>
                  <span className="ow-card-ico"><Users size={20} /></span><b>Không, mọi người chung một nhóm</b><small>Gọn nhất. Có thể chia {t.unit} sau.</small>
                </button>
                <button type="button" className={`ow-card is-wide${d.split ? ' is-on' : ''}`} onClick={() => set({ split: true })}>
                  <span className="ow-card-ico"><Building2 size={20} /></span><b>Có, chia theo {t.unit}</b><small>Mỗi {t.unit} có {t.MANAGER.toLowerCase()} và tài liệu nội bộ riêng.</small>
                </button>
              </div>
              {d.split && <div className="ow-units">
                <form className="ow-add" onSubmit={e => { e.preventDefault(); addUnits(unitText); setUnitText(''); }}>
                  <input autoFocus value={unitText} onChange={e => setUnitText(e.target.value)} placeholder={`Gõ tên ${t.unit} rồi nhấn Enter`} aria-label={`Tên ${t.unit}`} />
                  <button className="btn btn-ghost" disabled={!unitText.trim()}><Plus size={15} />Thêm</button>
                </form>
                {d.units.length > 0 && <div className="ow-chips">{d.units.map(u => <span key={u} className="ow-chip is-on">{u}
                  <button type="button" onClick={() => removeUnit(u)} aria-label={`Bỏ ${u}`}><X size={12} /></button></span>)}</div>}
                {UNIT_IDEAS[preset].some(u => !d.units.includes(u)) && <div className="ow-ideas"><span>Gợi ý:</span>
                  {UNIT_IDEAS[preset].filter(u => !d.units.includes(u)).map(u => <button key={u} type="button" className="ow-chip" onClick={() => addUnits(u)}><Plus size={12} />{u}</button>)}</div>}
              </div>}
            </>}

            {step === 3 && <>
              <form className="ow-add" onSubmit={e => { e.preventDefault(); addEmails(emailText); }}>
                <span className="ow-add-ico"><Mail size={16} /></span>
                <input autoFocus value={emailText} onChange={e => setEmailText(e.target.value)} onPaste={e => { e.preventDefault(); addEmails(emailText + ' ' + e.clipboardData.getData('text')); }}
                  placeholder="Nhập hoặc dán email, nhấn Enter" aria-label="Email người được mời" />
                <button className="btn btn-ghost" disabled={!emailText.trim()}><Plus size={15} />Thêm</button>
              </form>
              <p className="ow-hint">Người được mời cần có tài khoản. Họ nhận lời mời trong chuông thông báo.</p>
              {d.invitees.length > 0 && <ul className="ow-people">{d.invitees.map(i => <li key={i.email}>
                <span className="ow-avatar" aria-hidden="true">{i.email[0].toUpperCase()}</span>
                <span className="ow-email">{i.email}</span>
                <select value={i.level} onChange={e => editInvitee(i.email, { level: e.target.value as MemberLevel })} aria-label={`Cấp bậc của ${i.email}`}>
                  {(['STAFF', 'MANAGER', 'EXECUTIVE'] as MemberLevel[]).map(l => <option key={l} value={l}>{t.level[l]}</option>)}</select>
                {units.length > 1 && i.level !== 'EXECUTIVE' && <select value={i.unit ?? units[0]} onChange={e => editInvitee(i.email, { unit: e.target.value })} aria-label={`${t.Unit} của ${i.email}`}>
                  {units.map(u => <option key={u} value={u}>{u}</option>)}</select>}
                <button type="button" className="icon-btn is-sm" onClick={() => set({ invitees: d.invitees.filter(x => x.email !== i.email) })} aria-label={`Bỏ ${i.email}`}><X size={14} /></button>
              </li>)}</ul>}
              <label className={`ow-toggle${d.wantCode ? ' is-on' : ''}`}>
                <input type="checkbox" checked={d.wantCode} onChange={e => set({ wantCode: e.target.checked })} />
                <span className="ow-card-ico"><KeyRound size={18} /></span>
                <span><b>Tạo mã mời để gửi sau</b><small>Ai có mã đều xin vào được, bạn duyệt từng người.</small></span>
              </label>
            </>}

            {step === 4 && <div className="ow-review">
              <ReviewRow label="Loại hình" value={ORG_PRESETS[preset].name} onEdit={() => go(0)} />
              <ReviewRow label="Tên" value={d.name.trim()} onEdit={() => go(1)} />
              <ReviewRow label={t.Unit} value={units.length ? units.join(', ') : `Không chia, mọi người chung một ${t.unit}`} onEdit={() => go(2)} />
              <ReviewRow label="Mời" value={[d.invitees.length ? `${d.invitees.length} người` : 'Chưa mời ai', d.wantCode ? 'kèm mã mời' : ''].filter(Boolean).join(', ')} onEdit={() => go(3)} />
              <div className="ow-tree-inline"><OrgTree name={d.name} preset={preset} t={t} units={units} invitees={d.invitees} /></div>
            </div>}

            {step === 5 && result && <div className="ow-done">
              <NameCard big name={result.name} preset={preset} t={t} units={units} invitees={d.invitees} />
              <h3><PartyPopper size={20} aria-hidden="true" />{result.name} đã được tạo</h3>
              {result.code && <div className="ow-code"><span>Mã mời</span><code>{result.code}</code><CopyBtn text={result.code} /></div>}
              {d.invitees.length > 0 && <p className="ow-hint">Đã gửi lời mời tới {d.invitees.length - result.failed.length}/{d.invitees.length} người.</p>}
              {result.failed.length > 0 && <ul className="ow-failed">{result.failed.map(f => <li key={f.email}><b>{f.email}</b>: {f.reason}</li>)}</ul>}
              <div className="ow-done-acts">
                <button className="btn btn-dark" onClick={() => onOpen(result.spaceId)} data-autofocus><ArrowRight size={15} />Vào {t.org}</button>
                <button className="btn btn-ghost" onClick={onClose}>Đóng</button>
              </div>
            </div>}
            {error && <p className="note is-error" role="alert">{error}</p>}
          </div>
        </div>

        {!result && <aside className={`ow-preview${d.preset ? '' : ' is-dim'}`} aria-label={`Xem trước ${t.org} của bạn`}>
          <p className="ow-preview-t">Trang {t.org} của bạn</p>
          <NameCard name={d.name} preset={preset} t={t} units={units} invitees={d.invitees} />
          {step > 0 && <OrgTree name={d.name} preset={preset} t={t} units={units} invitees={d.invitees} />}
        </aside>}
      </div>
    </StudioModal>,
    document.querySelector('.st-app') ?? document.body,
  );
}

function ReviewRow({ label, value, onEdit }: { label: string; value: string; onEdit: () => void }) {
  return <div className="ow-rrow"><span>{label}</span><b>{value}</b><button type="button" className="btn btn-ghost is-sm" onClick={onEdit}>Sửa</button></div>;
}

function CopyBtn({ text }: { text: string }) {
  const [ok, setOk] = useState(false);
  return <button className="btn btn-ghost is-sm" onClick={async () => { await navigator.clipboard?.writeText(text).catch(() => undefined); setOk(true); }}>
    {ok ? <Check size={14} /> : <Copy size={14} />}{ok ? 'Đã chép' : 'Chép'}</button>;
}

// thẻ tên giống trang Tổng quan, cập nhật theo từng bước. Chỉ số thật: bạn là 1 thành viên, số đơn vị và số người sẽ mời đúng như đã nhập.
function NameCard({ name, preset, t, units, invitees, big }: { name: string; preset: OrgPreset; t: ReturnType<typeof orgTerms>; units: string[]; invitees: Invitee[]; big?: boolean }) {
  const Icon = PRESET_ICON[preset];
  return <div className={`ow-name${big ? ' is-big' : ''}`}>
    <img className="ow-name-art" src={coverOf(preset)} alt="" key={preset} />
    <span className="ow-name-tag"><Icon size={12} aria-hidden="true" />{ORG_PRESETS[preset].name} · {t.EXECUTIVE}</span>
    <b className={name.trim() ? '' : 'is-ph'}>{name.trim() || EXAMPLE_NAME[preset]}</b>
    <span className="ow-name-kpis">
      <span><b>1</b>thành viên</span>
      {units.length > 1 && <span><b>{units.length}</b>{t.unit}</span>}
      {invitees.length > 0 && <span><b>{invitees.length}</b>sẽ mời</span>}
    </span>
  </div>;
}

function OrgTree({ name, preset, t, units, invitees }: { name: string; preset: OrgPreset; t: ReturnType<typeof orgTerms>; units: string[]; invitees: Invitee[] }) {
  const shown = units.length ? units : [`${t.Unit} chung`];
  const people = (u: string | null, lv?: MemberLevel) => invitees.filter(i => (lv ? i.level === lv : i.level !== 'EXECUTIVE') && (u === null || (i.unit ?? shown[0]) === u)).length;
  const execs = people(null, 'EXECUTIVE') + 1;
  return <div className="ow-tree" aria-label={`Sơ đồ ${name.trim() || t.org}`}>
    <div className="ow-node is-exec"><span><b>{t.EXECUTIVE}</b><small>Bạn{execs > 1 ? ` + ${execs - 1} người` : ''} · xem được mọi tài liệu</small></span></div>
    <ul>{shown.map(u => { const n = people(u); return <li key={u} className="ow-node">
      <span><b>{u}</b><small>{t.MANAGER} · {t.STAFF}{n ? ` · ${n} người được mời` : ''}</small></span></li>; })}</ul>
  </div>;
}

