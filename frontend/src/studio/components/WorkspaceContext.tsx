// Cột ngữ cảnh bên phải của Không gian làm việc. Làm lại 21/11 theo mẫu "nguồn đánh số + đoạn trích xem trước"
// (kiểu bảng nguồn của các trợ lý có trích dẫn): mỗi đoạn được dùng là một thẻ có số, tên tài liệu, loại và 2 dòng trích;
// bấm thẻ mở đoạn đầy đủ (có tô từ khóa, chuyển qua lại giữa các nguồn). Tab "Quá trình" gộp các bước thật thành 4 giai đoạn.
// Điện thoại: ngăn kéo từ dưới lên (giữ như cũ).
import React, { useEffect, useMemo, useState } from 'react';
import { BookOpen, Check, ChevronDown, ChevronLeft, ChevronRight, Clock, Copy, Cpu, ExternalLink, FolderCog, Layers, ListChecks, Play, Sparkles, Users, X } from 'lucide-react';
import { DOC_TYPES, DocValidity, documentValidity, getChunk, SKILL_LIST, SkillKey } from '../services/api';
import { FileIcon } from './FileIcon';
import { highlightParts, keyTerms, suggestSkills, traceOf } from '../utils/workspaceAssist';

export type CtxTab = 'sources' | 'process';
type Doc = { id?: number | string; source_file: string; chunks_count: number; doc_type?: string | null };
// tên tác tử/lĩnh vực máy chủ trả về → tiếng Việt; tên lạ thì bỏ gạch dưới
const AGENT_VI: Record<string, string> = {
  conditions: 'Điều kiện', procedure: 'Quy trình', terms: 'Điều khoản', figures: 'Số liệu', general: 'Tổng hợp',
  api_architecture: 'Kiến trúc API', database: 'Cơ sở dữ liệu', security: 'Bảo mật', frontend: 'Giao diện', backend: 'Máy chủ',
  requirements: 'Yêu cầu', testing: 'Kiểm thử', deployment: 'Triển khai', performance: 'Hiệu năng',
};
const agentName = (a: string) => AGENT_VI[a] ?? a.replace(/Agent$/, '').replace(/_/g, ' ');
const docTitle = (f: string) => f.replace(/\.[^.]+$/, '').replace(/_/g, ' ');
// đoạn gốc thường là Markdown: bỏ dấu tiêu đề, kẻ bảng, in đậm để đọc như văn bản (chỉ để hiển thị, không đổi dữ liệu)
const plain = (t: string) => t.replace(/^\s*#{1,6}\s*/gm, '').replace(/^\s*\|?[\s:|-]{3,}\|?\s*$/gm, '').replace(/\s*\|\s*/g, ' · ').replace(/[*`]+/g, '').replace(/\n{3,}/g, '\n\n').trim();

const fmtDate = (d?: string | null) => { if (!d) return ''; const m = d.match(/^(\d{4})-(\d{2})-(\d{2})/); return m ? `${m[3]}/${m[2]}/${m[1]}` : d; };
const fold = (v: string) => v.normalize('NFD').replace(/\p{M}/gu, '').replace(/đ/gi, 'd').toLowerCase();
/** Tiêu đề của một đoạn: dòng tiêu đề Markdown đầu tiên, không có thì câu đầu (để đặt tên trong danh sách chọn). */
function passageTitle(text: string): string {
  const h = text.match(/^\s*#{1,6}\s*(.+)$/m)?.[1] ?? text.split('\n').find(l => l.trim())?.trim() ?? '';
  const t = h.replace(/[*`|#]+/g, '').trim();
  return t.length > 64 ? t.slice(0, 62) + '…' : t;
}
type Block = { kind: 'h' | 'p' | 'li' | 'row'; text: string };
function blocksOf(text: string): Block[] {
  const out: Block[] = [];
  for (const raw of text.split('\n')) {
    const l = raw.trim();
    if (!l || /^\|?[\s:|-]{3,}\|?$/.test(l)) continue;
    const h = l.match(/^#{1,6}\s*(.+)$/), li = l.match(/^[-*+]\s+(.+)$/) ?? l.match(/^\d+[.)]\s+(.+)$/);
    if (h) out.push({ kind: 'h', text: h[1] });
    else if (/^\|.*\|$/.test(l)) out.push({ kind: 'row', text: l.slice(1, -1).split('|').map(c => c.trim()).filter(Boolean).join(' · ') });
    else if (li) out.push({ kind: 'li', text: li[1] });
    else out.push({ kind: 'p', text: l });
  }
  return out;
}
/** Chữ trong một khối: **đậm** thành chữ đậm, từ khóa câu hỏi được tô; dấu Markdown thừa bị bỏ. */
function Inline({ text, terms }: { text: string; terms: string[] }) {
  return <>{text.split(/(\*\*[^*]+\*\*)/).map((seg, i) => {
    const bold = /^\*\*[^*]+\*\*$/.test(seg), t = (bold ? seg.slice(2, -2) : seg).replace(/[*`]+/g, '');
    const parts = highlightParts(t, terms).map((p, k) => p.hit ? <mark key={k}>{p.t}</mark> : <React.Fragment key={k}>{p.t}</React.Fragment>);
    return bold ? <strong key={i}>{parts}</strong> : <React.Fragment key={i}>{parts}</React.Fragment>;
  })}</>;
}
function Passage({ text, terms }: { text: string; terms: string[] }) {
  const blocks = blocksOf(text);
  // dòng có nhiều từ khóa câu hỏi nhất (ít nhất 2) được tô nền: chỗ người đọc cần nhìn trước
  const score = (b: Block) => new Set(b.text.split(/[^\p{L}\p{N}]+/u).map(fold).filter(w => terms.includes(w))).size;
  let key = -1, best = 1;
  blocks.forEach((b, i) => { const sc = b.kind === 'h' ? 0 : score(b); if (sc > best) { best = sc; key = i; } });
  const out: React.ReactNode[] = []; let list: React.ReactNode[] = [];
  const flush = () => { if (list.length) { out.push(<ul key={`u${out.length}`}>{list}</ul>); list = []; } };
  blocks.forEach((b, i) => {
    const cls = i === key ? 'is-key' : undefined, body = <Inline text={b.text} terms={terms} />;
    if (b.kind === 'li') { list.push(<li key={i} className={cls}>{body}</li>); return; }
    flush();
    out.push(b.kind === 'h' ? <h4 key={i}>{body}</h4> : <p key={i} className={[cls, b.kind === 'row' ? 'is-row' : ''].filter(Boolean).join(' ') || undefined}>{body}</p>);
  });
  flush();
  return <div className="cx-pass">{out}</div>;
}

/** Mục có dải tiêu đề bấm để thu/mở (như bản phác của nhóm). */
function Sect({ title, icon, open: initial = true, children, right }: { title: React.ReactNode; icon?: React.ReactNode; open?: boolean; children: React.ReactNode; right?: React.ReactNode }) {
  const [open, setOpen] = useState(initial);
  useEffect(() => setOpen(initial), [initial]);  // mặc định đổi theo dữ liệu (vd. nguồn vừa tải xong)
  return <section className={`cx-sect${open ? ' is-open' : ''}`}>
    <button type="button" className="cx-sect-h" onClick={() => setOpen(o => !o)} aria-expanded={open}>
      <ChevronDown size={16} className="cx-sect-chev" aria-hidden="true" />{icon}<span>{title}</span>{right}
    </button>
    {open && <div className="cx-sect-b">{children}</div>}
  </section>;
}

// gộp các bước thật (nhãn của progressLabel) thành giai đoạn; bước không khớp nhóm nào vào "Hiểu câu hỏi"
type Phase = { key: string; title: string; steps: string[] };
function phasesOf(steps: string[]): Phase[] {
  const ph: Record<string, Phase> = {
    understand: { key: 'understand', title: 'Hiểu yêu cầu', steps: [] },
    plan: { key: 'plan', title: 'Lập và kiểm tra kế hoạch', steps: [] },
    agents: { key: 'agents', title: 'Tác tử đọc tài liệu', steps: [] },
    write: { key: 'write', title: 'Viết câu trả lời', steps: [] },
  };
  for (const s of steps) {
    if (/kế hoạch/i.test(s)) ph.plan.steps.push(s);
    else if (/^(Nhiệm vụ|Tác tử)/.test(s)) ph.agents.steps.push(s);
    else if (/viết câu trả lời/i.test(s)) ph.write.steps.push(s);
    else ph.understand.steps.push(s);
  }
  return Object.values(ph).filter(p => p.steps.length);
}
function phaseNote(p: Phase): string {
  if (p.key === 'plan') {
    const rounds = p.steps.filter(s => /lập kế hoạch nhiều bước/i.test(s)).length;
    const ok = p.steps.some(s => /Kế hoạch đạt/.test(s)), bad = p.steps.some(s => /chưa qua/.test(s));
    return `${rounds > 1 ? `${rounds} vòng lập và kiểm tra` : 'Một vòng lập và kiểm tra'}${ok ? ' · kế hoạch đạt' : bad ? ' · chưa qua kiểm tra' : ''}`;
  }
  if (p.key === 'agents') {
    const done = p.steps.filter(s => /xong$/.test(s)).length, total = p.steps.filter(s => /đang đọc/.test(s)).length || done;
    return `${done}/${total} nhiệm vụ xong`;
  }
  return p.steps[p.steps.length - 1];
}

interface Props {
  tab: CtxTab;
  onTab: (t: CtxTab) => void;
  docs: Doc[];
  /** tài liệu được chọn để trả lời; rỗng = cả không gian */
  picked: string[];
  onPick: (ids: string[]) => void;
  chunk: { id: string; source?: string; sourceId?: string; text?: string; error?: string } | null;
  question?: string;
  onCloseChunk: () => void;
  onOpenFull?: (sourceId: string, name?: string) => void;
  run?: Parameters<typeof traceOf>[0];
  live?: { steps: string[]; elapsed: number } | null;
  draft: string;
  onUseSkill: (k: SkillKey) => void;
  manage?: React.ReactNode;
  mobileOpen: boolean;
  onMobileClose: () => void;
  /** nguồn của lượt trả lời đang xem (mã đoạn + nhãn) */
  cites?: { id: string; label: string }[];
  onCite?: (id: string) => void;
  collapsed: boolean;
  onCollapse: (v: boolean) => void;
}

export const WorkspaceContext: React.FC<Props> = ({ tab, onTab, docs, picked, onPick, chunk, question = '', onCloseChunk, onOpenFull, run, live, draft, onUseSkill, manage, mobileOpen, onMobileClose, cites = [], onCite, collapsed, onCollapse }) => {
  const ids = useMemo(() => docs.map(d => String(d.id ?? '')).filter(Boolean), [docs]);
  // nhãn bản cũ/mới: luật đọc số hiệu và "thay thế" trong văn bản (không gọi mô hình)
  const [validity, setValidity] = useState<Record<string, DocValidity>>({});
  useEffect(() => {
    if (!ids.length) { setValidity({}); return; }
    let alive = true;
    documentValidity(ids.slice(0, 40)).then(r => alive && setValidity(Object.fromEntries(r.documents.map(d => [d.source_id, d])))).catch(() => alive && setValidity({}));
    return () => { alive = false; };
  }, [ids.join(',')]);
  const all = picked.length === 0;
  const scopeTypes = docs.filter(d => all || picked.includes(String(d.id))).map(d => d.doc_type);
  const trace = traceOf(run);
  const terms = useMemo(() => keyTerms(question), [question]);

  // nguồn đánh số: mỗi đoạn một thẻ; đoạn trích xem trước lấy từ máy chủ (tối đa 8 đoạn, lưu lại theo mã)
  const sources = useMemo(() => cites.slice(0, 12).map((c, i) => {
    const sid = c.id.replace(/_c\d+$/, ''), doc = docs.find(d => String(d.id) === sid);
    const part = c.label.match(/đoạn\s*\d+/)?.[0];
    return { n: i + 1, id: c.id, sid, name: doc ? docTitle(doc.source_file) : c.label.replace(/\s*·\s*đoạn.*$/, ''), part, type: doc?.doc_type ? DOC_TYPES[doc.doc_type] ?? doc.doc_type : undefined };
  }), [cites, docs]);
  // toàn văn từng đoạn được trích (tối đa 8), lưu theo mã; null = đang tải, '' = lỗi
  const [texts, setTexts] = useState<Record<string, string | null>>({});
  useEffect(() => {
    const need = sources.slice(0, 8).filter(s => !(s.id in texts));
    if (!need.length) return;
    setTexts(m => ({ ...m, ...Object.fromEntries(need.map(s => [s.id, null])) }));
    need.forEach(s => getChunk(s.id).then(r => setTexts(m => ({ ...m, [s.id]: r.text }))).catch(() => setTexts(m => ({ ...m, [s.id]: '' }))));
  }, [sources.map(s => s.id).join(',')]);
  // đoạn đang xem: bấm nguồn trong câu trả lời thì theo đó, không thì mở sẵn nguồn 1
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => { if (chunk?.id) setSel(chunk.id); }, [chunk?.id]);
  const cur = sources.find(s => s.id === sel) ?? sources[0];
  const at = cur ? sources.indexOf(cur) : -1;
  const curText = cur ? (chunk?.id === cur.id && chunk.text != null ? chunk.text : texts[cur.id]) : undefined;
  const [copied, setCopied] = useState(false);
  const copyCite = () => { if (!cur || !curText) return; void navigator.clipboard?.writeText(`"${plain(curText)}"\n(${cur.name}${cur.part ? `, ${cur.part}` : ''})`).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1600); }); };
  // tài liệu đã dùng: gộp các đoạn theo tài liệu, kèm ngày ban hành/hiệu lực và nhãn bản cũ/mới nếu hệ thống đọc được
  const used = useMemo(() => {
    const m = new Map<string, { sid: string; name: string; file: string; type?: string; n: number[]; first: string }>();
    for (const s of sources) {
      const doc = docs.find(d => String(d.id) === s.sid);
      if (!m.has(s.sid)) m.set(s.sid, { sid: s.sid, name: s.name, file: doc?.source_file ?? '', type: s.type, n: [], first: s.id });
      m.get(s.sid)!.n.push(s.n);
    }
    return [...m.values()];
  }, [sources, docs]);
  const citedTypes = used.map(u => docs.find(d => String(d.id) === u.sid)?.doc_type);
  const skills = suggestSkills(citedTypes.some(Boolean) ? citedTypes : scopeTypes, draft || question);
  // thu gọn: có nguồn mới trong lúc cột đang gấp → nút Nguồn sáng lên vài giây
  const citeKey = cites.map(c => c.id).join(',');
  const [fresh, setFresh] = useState(false);
  const prevKey = React.useRef(citeKey);
  useEffect(() => {
    if (citeKey === prevKey.current) return;
    prevKey.current = citeKey;
    if (!collapsed || !citeKey) return;
    setFresh(true); const t = window.setTimeout(() => setFresh(false), 6000);
    return () => window.clearTimeout(t);
  }, [citeKey]);
  const phases = phasesOf(trace?.steps ?? []);
  const livePhases = live ? phasesOf(live.steps) : [];
  const [rawOpen, setRawOpen] = useState(false);

  // nút tròn trên mép trái, giống nút thu gọn của thanh bên trái
  const edge = <button type="button" className="cx-edge" onClick={() => onCollapse(!collapsed)} aria-label={collapsed ? 'Mở rộng cột ngữ cảnh' : 'Thu gọn cột ngữ cảnh'} title={collapsed ? 'Mở rộng' : 'Thu gọn'}>
    {collapsed ? <ChevronLeft size={15} strokeWidth={2.4} /> : <ChevronRight size={15} strokeWidth={2.4} />}</button>;

  // thu gọn: không giữ cột trống; chỉ còn một viên nhỏ nổi ở góc trên phải khung chat (khung chat rộng hết cỡ)
  if (collapsed && !mobileOpen) return (
    <aside className={`cx-pill${fresh ? ' is-new' : ''}`} aria-label="Ngữ cảnh câu trả lời (đã thu gọn)">
      <button type="button" onClick={() => { onTab('sources'); onCollapse(false); }} aria-label={cites.length ? `Mở Nguồn và tài liệu, ${cites.length} đoạn` : 'Mở Nguồn và tài liệu'} title="Mở cột Nguồn & Tài liệu">
        <BookOpen size={16} /><span>Nguồn</span>{cites.length > 0 && <i>{cites.length}</i>}</button>
      <button type="button" onClick={() => { onTab('process'); onCollapse(false); }} aria-label="Mở Quá trình xử lý" title="Mở cột Quá trình xử lý">
        <ListChecks size={16} /><span>Quá trình</span>{live && <i className="is-live" />}</button>
      <button type="button" className="cx-pill-open" onClick={() => onCollapse(false)} aria-label="Mở rộng cột ngữ cảnh" title="Mở rộng"><ChevronLeft size={16} strokeWidth={2.4} /></button>
    </aside>
  );

  const usedIds = new Set(used.map(u => u.sid));
  const ordered = [...docs].sort((a, b) => Number(usedIds.has(String(b.id))) - Number(usedIds.has(String(a.id))));
  const docList = <ul className="cx-kb">{ordered.map(d => {
    const id = String(d.id ?? ''), on = usedIds.has(id), v = validity[id], u = used.find(x => x.sid === id);
    return <li key={id} className={on ? 'is-used' : ''}>
      <FileIcon name={d.source_file} size={24} />
      <span className="cx-src"><b title={d.source_file}>{docTitle(d.source_file)}</b>
        <small>{d.chunks_count} đoạn{d.doc_type ? ` · ${DOC_TYPES[d.doc_type] ?? d.doc_type}` : ''}</small></span>
      {on ? <em className="cx-tag is-use" title={`Câu trả lời dùng ${u?.n.length ?? 0} đoạn của tài liệu này`}><Check size={11} strokeWidth={3} />Đã dùng{u && u.n.length > 1 ? ` ${u.n.length}` : ''}</em>
        : v?.status === 'REPLACED' ? <em className="cx-tag is-old" title={v.status_note}>Bản cũ</em> : null}
    </li>;
  })}</ul>;
  const versions = used.filter(u => validity[u.sid]?.status === 'REPLACED' || (validity[u.sid]?.replaces.length ?? 0) > 0).length;
  const usedTitle = used.length === 2 && versions === 2 ? 'Hai phiên bản đã sử dụng' : `Tài liệu đã sử dụng (${used.length})`;

  return (
    <>
      {mobileOpen && <div className="wc-scrim" onClick={onMobileClose} />}
      <aside className={`wc cx${mobileOpen ? ' is-open' : ''}`} aria-label="Ngữ cảnh câu trả lời">
        {edge}
        <div className="wc-grab" aria-hidden="true" />
        <div className="cx-tabs" role="tablist" aria-label="Ngữ cảnh">
          <button role="tab" aria-selected={tab === 'sources'} className={tab === 'sources' ? 'is-on' : ''} onClick={() => onTab('sources')}>Nguồn & Tài liệu{cites.length > 0 && <i className="cx-count">{cites.length}</i>}</button>
          <button role="tab" aria-selected={tab === 'process'} className={tab === 'process' ? 'is-on' : ''} onClick={() => onTab('process')}>Quá trình xử lý{live && <i className="wc-live" aria-label="đang chạy" />}</button>
          <button className="wc-x" onClick={onMobileClose} aria-label="Đóng ngữ cảnh"><X size={18} /></button>
        </div>

        <div className="wc-body cx-body" role="tabpanel">
          {tab === 'sources' ? <>
            {used.length > 0 && <Sect title={usedTitle}>
              <ul className="cx-used">{used.map(u => {
                const v = validity[u.sid];
                const dates = [v?.issued && `Ban hành: ${fmtDate(v.issued)}`, v?.effective && `Hiệu lực: ${fmtDate(v.effective)}`].filter(Boolean).join(' · ');
                return <li key={u.sid}><button type="button" className={cur?.sid === u.sid ? 'is-on' : ''} onClick={() => setSel(u.first)}>
                  <FileIcon name={u.file || '.md'} />
                  <span className="cx-src"><b title={u.name}>{u.name}</b>
                    <small>{dates || [u.type, `${u.n.length} đoạn được trích`].filter(Boolean).join(' · ')}</small></span>
                  {v?.status === 'REPLACED' ? <em className="cx-tag is-old" title={v.status_note}>Bản cũ</em>
                    : v && v.replaces.length > 0 ? <em className="cx-tag is-new" title={`Thay thế ${v.replaces.join(', ')}`}>Bản mới</em> : null}
                </button></li>;
              })}</ul>
            </Sect>}

            {cur && <Sect title="Trích dẫn liên quan">
              <div className="cx-pick">
                <select value={cur.id} onChange={e => setSel(e.target.value)} aria-label="Chọn trích dẫn">
                  {sources.map(s => <option key={s.id} value={s.id}>{texts[s.id] ? passageTitle(texts[s.id]!) : s.name} ({s.part ?? s.name})</option>)}
                </select>
                <ChevronDown size={16} className="cx-pick-chev" aria-hidden="true" />
              </div>
              <div className="cx-card">
                <div className="cx-doc">
                  {curText == null ? <p className="cx-load"><span className="spin is-dark" />Đang tải đoạn…</p>
                    : curText === '' ? <p className="note is-error">Không tải được đoạn này.</p>
                    : <Passage text={curText} terms={terms} />}
                </div>
                <div className="cx-acts">
                  {onOpenFull ? <button type="button" onClick={() => onOpenFull(cur.sid, cur.name)}><ExternalLink size={14} />Xem toàn văn</button> : <span />}
                  {sources.length > 1 && <span className="cx-nav">
                    <button type="button" disabled={at <= 0} onClick={() => setSel(sources[at - 1].id)} aria-label="Trích dẫn trước"><ChevronLeft size={15} /></button>
                    <small>{at + 1}/{sources.length}</small>
                    <button type="button" disabled={at >= sources.length - 1} onClick={() => setSel(sources[at + 1].id)} aria-label="Trích dẫn sau"><ChevronRight size={15} /></button></span>}
                  <button type="button" onClick={copyCite} disabled={!curText}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Đã chép' : 'Sao chép trích dẫn'}</button>
                </div>
              </div>
            </Sect>}

            {skills.length > 0 && <Sect title="Kỹ năng đề xuất" icon={<Sparkles size={15} className="cx-sect-ico" />}>
              <div className="cx-card cx-skills">{skills.map(s => { const k = SKILL_LIST.find(x => x.key === s.key);
                return <button key={s.key} type="button" onClick={() => onUseSkill(s.key)} title={s.why}>
                  <span className="cx-ico"><Sparkles size={16} /></span>
                  <span className="cx-src"><b>{k?.label}</b><small>{k?.hint}</small></span>
                  <Play size={13} className="cx-go" fill="currentColor" aria-hidden="true" /></button>; })}</div>
            </Sect>}

            <Sect title="Tài liệu trong không gian" icon={<Layers size={15} className="cx-sect-ico" />} open={sources.length === 0}
              right={<small className="cx-sect-r">{docs.length === 0 ? 'Chưa có' : used.length ? `Dùng ${used.length}/${docs.length}` : `${docs.length} tài liệu`}</small>}>
              {docs.length === 0 ? <ol className="cx-guide">
                  <li><b>Tải tài liệu lên</b><small>PDF, Word, Excel hoặc ảnh chụp, bằng nút ở giữa màn hình hoặc mục Kho tài liệu bên dưới.</small></li>
                  <li><b>Đặt câu hỏi</b><small>C27 tự tìm trong mọi tài liệu của không gian; tài liệu được dùng sẽ được đánh dấu ở đây.</small></li>
                  <li><b>Xem trích dẫn</b><small>Đoạn gốc hiện ở cột này, dòng khớp câu hỏi được tô.</small></li>
                </ol>
                : <div className="cx-card">{live && <p className="cx-kb-live"><span className="spin is-dark" />Đang tìm trong {docs.length} tài liệu…</p>}{docList}</div>}
            </Sect>

            {manage && <Sect title="Kho tài liệu" icon={<FolderCog size={15} className="cx-sect-ico" />} open={false}>{manage}</Sect>}
          </> : <>
            {(live || trace) && <dl className="cx-metrics">
              <div><dt><Clock size={13} />Thời gian</dt><dd>{live ? `${live.elapsed} giây` : trace!.ms == null ? 'Chưa đo' : `${(trace!.ms / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây`}</dd></div>
              <div><dt><Cpu size={13} />Token</dt><dd>{live || trace!.tokens == null ? 'Chưa đo' : trace!.tokens.toLocaleString('vi-VN')}</dd></div>
              <div><dt><Users size={13} />Nhiệm vụ</dt><dd>{live ? '…' : trace!.tasks}</dd></div>
            </dl>}

            {(live ? livePhases : phases).length > 0 && <Sect title={live ? 'Đang xử lý' : 'Lượt trả lời gần nhất'}>
              <div className="cx-card cx-pad" aria-live={live ? 'polite' : undefined}>
                <ol className="cx-time">{(live ? livePhases : phases).map((p, i, arr) => {
                  const now = !!live && i === arr.length - 1;
                  return <li key={p.key} className={now ? 'is-now' : 'is-done'}>
                    <span className="cx-dot" aria-hidden="true">{now ? <i /> : <Check size={12} strokeWidth={3} />}</span>
                    <div><b>{p.title}</b><small>{phaseNote(p)}</small>
                      {p.key === 'agents' && !live && trace!.agents.length > 0 && <span className="cx-agents">{trace!.agents.map(a => <em key={a}>{agentName(a)}</em>)}</span>}</div>
                  </li>;
                })}</ol>
                {!live && trace!.steps.length > 0 && <>
                  <button type="button" className="cx-raw-t" onClick={() => setRawOpen(o => !o)} aria-expanded={rawOpen}><ChevronDown size={14} className={`cx-chev${rawOpen ? ' is-up' : ''}`} />{rawOpen ? 'Ẩn' : 'Xem'} {trace!.steps.length} bước chi tiết</button>
                  {rawOpen && <ol className="cx-raw">{trace!.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
                </>}
              </div>
            </Sect>}

            {live && live.steps.length === 0 && <p className="cx-empty"><span className="spin is-dark" />Đã gửi yêu cầu, chờ máy chủ báo bước đầu tiên…</p>}
            {!live && trace && trace.steps.length === 0 && <p className="cx-empty">Lượt này không ghi sự kiện tiến trình (ví dụ thẻ kỹ năng).</p>}
            {!live && !trace && <div className="cx-blank"><span><ListChecks size={24} /></span><b>Chưa có lượt trả lời</b><p>Gửi câu hỏi để xem hệ thống đã hiểu, lập kế hoạch và đọc tài liệu thế nào.</p></div>}
          </>}
        </div>
      </aside>
    </>
  );
};
