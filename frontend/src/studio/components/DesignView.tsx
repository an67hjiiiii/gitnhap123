import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Circle, Copy, Download, KeyRound, ListTree, Loader2, PencilRuler, Save, Square, StickyNote, X, XCircle, Workflow } from 'lucide-react';
import './profile/tools.css';
import {
  DesignCoverage, DesignDomain, DesignPoint, DesignSectionResult, designCoverage, designPoints, designSection, getReport, canSaveReports, saveReport,
} from '../services/api';
import { baseName, chunkLabel, DistributionBar, Doc, DocPicker, docId, download, EmptyState, fmtSeconds, ProcessRail, SavedReportsSelect, ToolHeader, useAnalysisData, useChunkViewer } from './analysis/shared';

const DOMAINS: DesignDomain[] = ['database', 'api_architecture', 'security'];
const DOMAIN_VI: Record<DesignDomain, string> = { database: 'Cơ sở dữ liệu', api_architecture: 'API và tích hợp', security: 'Bảo mật' };
const COVER: Record<DesignCoverage['status'], { label: string; tone: string }> = {
  COVERED: { label: 'Đã bao phủ', tone: 'complete' }, PARTIAL: { label: 'Một phần', tone: 'partial' }, MISSING: { label: 'Chưa có', tone: 'failed' },
};
const PRESETS = [
  'Thêm chức năng cho Merchant Owner tạo yêu cầu hoàn tiền một phần cho một đơn đã thanh toán; hoàn tiền từ 10 triệu đồng phải được Finance duyệt; không được hoàn vượt số tiền đã thanh toán; mọi thao tác phải được ghi nhật ký kiểm toán.',
  'Cho merchant tự xoay vòng khóa ký webhook: tạo khóa mới, khóa cũ còn hiệu lực song song 24 giờ, chỉ Merchant Owner được thao tác, mọi lần xoay khóa ghi nhật ký.',
  'Xuất báo cáo đối soát cuối ngày dạng CSV cho bộ phận Finance: lọc theo ngày và ngân hàng, chỉ vai trò Finance được tải, giới hạn tần suất và ghi lại ai đã tải.',
];
type StepKey = 'points' | DesignDomain | 'coverage';
type Step = { state: 'wait' | 'run' | 'done' | 'error'; info?: string; m?: { input_tokens: number; output_tokens: number; latency_ms: number }; shared?: number; evidence?: number };
const STEP_LABEL: Record<StepKey, string> = { points: 'Phân tích ý chính', database: 'Tác tử CSDL', api_architecture: 'Tác tử API', security: 'Tác tử Bảo mật', coverage: 'Kiểm tra độ phủ' };
const ORDER: StepKey[] = ['points', ...DOMAINS, 'coverage'];
const fresh = (): Record<StepKey, Step> => Object.fromEntries(ORDER.map(k => [k, { state: 'wait' }])) as Record<StepKey, Step>;

function Grounded({ item, onShow, sources }: { item: { citations: string[]; grounded: boolean }; onShow: (id: string) => void; sources: Record<string, string> }) {
  return item.grounded
    ? <span className="dz-badge is-grounded" title="Dựa trên tài liệu tham chiếu">Có căn cứ{item.citations.map(c => <button key={c} onClick={() => onShow(c)}>{chunkLabel(c, sources[c])}</button>)}</span>
    : <span className="dz-badge is-new" title="Tác tử đề xuất thêm, không có trong tài liệu">Đề xuất mới</span>;
}

export const DesignView: React.FC<{ workspaceId: number | string; docs: Doc[] }> = ({ workspaceId, docs }) => {
  const { allDocs, saved, refreshSaved } = useAnalysisData('design');
  const viewer = useChunkViewer();
  const [request, setRequest] = useState('');
  const [refs, setRefs] = useState<Set<string>>(new Set());
  const [steps, setSteps] = useState(fresh);
  const [points, setPoints] = useState<DesignPoint[]>([]);
  const [sections, setSections] = useState<Partial<Record<DesignDomain, DesignSectionResult>>>({});
  const [coverage, setCoverage] = useState<DesignCoverage[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [tab, setTab] = useState<'overview' | DesignDomain | 'export'>('overview');
  const [copied, setCopied] = useState<string | null>(null);
  const stop = useRef(false);

  useEffect(() => { if (refs.size === 0 && docs.length) setRefs(new Set(docs.map(docId))); }, [docs]);
  const pickable = allDocs.length ? allDocs : docs;
  const refIds = [...refs].filter(Boolean);
  const sources = useMemo(() => Object.fromEntries(Object.values(sections).flatMap(s => s!.evidence.map(e => [e.chunk_id, e.source_name]))), [sections]);
  const measured = Object.values(steps).reduce((a, s) => ({ tok: a.tok + (s.m ? s.m.input_tokens + s.m.output_tokens : 0), ms: a.ms + (s.m?.latency_ms ?? 0) }), { tok: 0, ms: 0 });
  const shared = DOMAINS.reduce((n, d) => n + (sections[d]?.shared_chunks ?? 0), 0);
  const done = coverage.length > 0;
  const cnt = (s: DesignCoverage['status']) => coverage.filter(c => c.status === s).length;
  const setStep = (k: StepKey, s: Step) => setSteps(prev => ({ ...prev, [k]: s }));

  const run = async () => {
    const text = request.trim();
    if (text.length < 10) { setError('Mô tả yêu cầu tính năng cụ thể hơn (ít nhất 10 ký tự).'); return; }
    stop.current = false; setRunning(true); setError(null); setNote(null); setSteps(fresh()); setPoints([]); setSections({}); setCoverage([]); setTab('overview');
    let current: StepKey = 'points';
    try {
      setStep('points', { state: 'run' });
      const p = await designPoints(text);
      setPoints(p.points); setStep('points', { state: 'done', m: p, info: `${p.points.length} ý chính${p.flags.length ? ' · không tách được, giữ nguyên yêu cầu' : ''}` });
      const used: string[] = []; const got: Record<string, any> = {};
      for (const d of DOMAINS) {
        if (stop.current) throw new Error('Đã dừng theo yêu cầu.');
        current = d; setStep(d, { state: 'run' });
        const s = await designSection(text, d, p.points, refIds, used);
        used.push(...s.evidence.map(e => e.chunk_id)); got[d] = s.section;
        setSections(prev => ({ ...prev, [d]: s }));
        setStep(d, { state: 'done', m: s, shared: s.shared_chunks, evidence: s.evidence.length, info: s.flags.includes('empty_section') ? 'Tác tử không đưa ra nội dung' : undefined });
      }
      if (stop.current) throw new Error('Đã dừng theo yêu cầu.');
      current = 'coverage'; setStep('coverage', { state: 'run' });
      const c = await designCoverage(text, p.points, got);
      setCoverage(c.coverage); setStep('coverage', { state: 'done', m: c });
    } catch (e: any) {
      setStep(current, { state: 'error', info: e.message }); setError(e.message);
    } finally { setRunning(false); }
  };

  const markdown = () => {
    const L: string[] = [`# Gói thiết kế kỹ thuật`, '', `**Yêu cầu:** ${request.trim()}`, '', `Tài liệu tham chiếu: ${refIds.map(id => pickable.find(d => docId(d) === id)?.source_file ?? id).join(', ') || 'không'}`, '',
      '## 1. Ý chính và độ phủ', '', '| Ý | Nội dung | Chuyên môn | Độ phủ | Phần thiết kế | Ghi chú |', '|---|---|---|---|---|---|',
      ...points.map(p => { const c = coverage.find(x => x.point_id === p.id); return `| ${p.id} | ${p.text} | ${DOMAIN_VI[p.domain]} | ${c ? COVER[c.status].label : '—'} | ${c?.sections.map(s => DOMAIN_VI[s]).join(', ') ?? ''} | ${c?.note ?? ''} |`; })];
    const tag = (x: any) => x.grounded ? `căn cứ: ${x.citations.map((c: string) => chunkLabel(c, sources[c])).join('; ')}` : 'đề xuất mới';
    const db = sections.database?.section; const api = sections.api_architecture?.section; const sec = sections.security?.section;
    if (db) {
      L.push('', '## 2. Cơ sở dữ liệu');
      db.tables.forEach((t: any) => L.push('', `### Bảng \`${t.name}\` (${tag(t)})`, t.purpose, '', '| Cột | Kiểu | Ràng buộc |', '|---|---|---|', ...t.columns.map((c: any) => `| ${c.name} | ${c.type} | ${c.constraints} |`)));
      if (db.indexes.length) L.push('', '**Chỉ mục:**', ...db.indexes.map((i: any) => `- ${i.table}(${i.columns}): ${i.purpose}`));
      db.notes.forEach((n: any) => L.push(`- ${n.text} (${tag(n)})`));
    }
    if (api) {
      L.push('', '## 3. API', '', '| Phương thức | Đường dẫn | Mục đích | Trường vào | Phản hồi | Nguồn |', '|---|---|---|---|---|---|',
        ...api.endpoints.map((e: any) => `| ${e.method} | \`${e.path}\` | ${e.purpose} | ${e.request.join('; ')} | ${e.responses.join('; ')} | ${tag(e)} |`));
      api.notes.forEach((n: any) => L.push(`- ${n.text} (${tag(n)})`));
    }
    if (sec) {
      L.push('', '## 4. Bảo mật', '', '| Rủi ro | Biện pháp | Nguồn |', '|---|---|---|', ...sec.controls.map((c: any) => `| ${c.risk} | ${c.control} | ${tag(c)} |`));
      if (sec.permissions.length) L.push('', '**Phân quyền:**', ...sec.permissions.map((p: any) => `- ${p.role}: ${p.actions.join('; ')}`));
      sec.notes.forEach((n: any) => L.push(`- ${n.text} (${tag(n)})`));
    }
    if (sections.database?.sql) L.push('', '## 5. Bản nháp SQL', '', '```sql', sections.database.sql.trim(), '```');
    if (sections.api_architecture?.openapi) L.push('', '## 6. Bản nháp OpenAPI', '', '```yaml', sections.api_architecture.openapi.trim(), '```');
    L.push('', `_Sinh bởi ba tác tử chạy cục bộ; ${measured.tok.toLocaleString('vi-VN')} token, ${fmtSeconds(measured.ms)} giây. Bản nháp cần kỹ sư rà soát._`);
    return L.join('\n');
  };
  const fileBase = `thiet-ke-${baseName(request.trim().slice(0, 40).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/gi, 'd').replace(/[^\w]+/g, '-').toLowerCase())}`;
  const save = async () => {
    setError(null);
    try {
      if (canSaveReports()) await saveReport({ kind: 'design', title: `Thiết kế · ${request.trim().slice(0, 60)}${request.trim().length > 60 ? '…' : ''}`, workspace_id: typeof workspaceId === 'string' && workspaceId ? workspaceId : null,
        payload: { request, refs: refIds, points, sections, coverage, steps } });
      await refreshSaved(); setNote('Đã lưu gói thiết kế.');
    } catch (e: any) { setError(e.message); }
  };
  const load = async (id: string) => {
    setError(null);
    try {
      const p = (await getReport(id)).payload;
      setRequest(p.request); setRefs(new Set(p.refs)); setPoints(p.points); setSections(p.sections); setCoverage(p.coverage); setSteps(p.steps); setTab('overview'); setNote('Đã mở gói thiết kế đã lưu.');
    } catch (e: any) { setError(e.message); }
  };
  const copy = async (key: string, text: string) => { try { await navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(null), 1500); } catch { setError('Trình duyệt chặn sao chép; hãy dùng nút tải tệp.'); } };

  const db = sections.database?.section; const api = sections.api_architecture?.section; const sec = sections.security?.section;
  const icon = (s: Step) => s.state === 'done' ? <CheckCircle2 size={16} className="is-ok" /> : s.state === 'run' ? <Loader2 size={16} className="is-spin" /> : s.state === 'error' ? <XCircle size={16} className="is-bad" /> : <Circle size={16} className="is-wait" />;

  return (
    <main className="pg tl tone-design">
      <div className="pg-col tv-col">
        <ToolHeader Icon={PencilRuler} title="Gói thiết kế kỹ thuật" desc="Từ một yêu cầu tính năng, ba tác tử viết thiết kế CSDL, API và bảo mật dựa trên tài liệu của bạn, rồi kiểm tra yêu cầu đã được bao phủ chưa."
          right={<SavedReportsSelect saved={saved} onLoad={load} disabled={running} />} />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span><button className="note-x" onClick={() => setError(null)} aria-label="Đóng thông báo"><X size={14} /></button></div>}
        {note && <p className="muted-line" role="status"><CheckCircle2 size={14} />{note}</p>}

        <section className="tv-setup dg-brief">
          <div className="dg-compose">
          <label className="tv-field"><span>Yêu cầu tính năng</span>
            <textarea className="dz-input" rows={4} value={request} onChange={e => setRequest(e.target.value)} disabled={running} maxLength={4000}
              placeholder="Ví dụ: Thêm chức năng hoàn tiền một phần; từ 10 triệu cần Finance duyệt; ghi nhật ký kiểm toán…" />
          </label>
          <div className="chips">{PRESETS.map((p, i) => <button key={i} type="button" className={`chip${request === p ? ' is-on' : ''}`} onClick={() => setRequest(p)} disabled={running}>Ví dụ {i + 1}</button>)}</div>
            <small className="dg-count">{request.trim().length}/4000 ký tự</small>
          </div>
          <div className="dg-refs"><DocPicker docs={pickable} selected={refs} onChange={setRefs} disabled={running} legend="Tài liệu tham chiếu" /></div>
          <div className="tv-actions">
            {running
              ? <button className="btn btn-danger" onClick={() => { stop.current = true; }}><Square size={14} />Dừng sau bước này</button>
              : <button className="btn btn-dark" onClick={run} disabled={request.trim().length < 10}><PencilRuler size={15} />{done ? 'Tạo lại gói thiết kế' : 'Tạo gói thiết kế'}</button>}
            {refIds.length === 0 && <span className="muted-line">Không chọn tài liệu: tác tử chỉ dựa vào yêu cầu, mọi mục sẽ là "đề xuất mới".</span>}
          </div>

        </section>
        <section className="dz-card dg-flow">
          <header><h3><Workflow size={16} />Đường đi của gói thiết kế</h3><small className="is-muted">{running ? 'Đang chạy…' : done ? `${fmtSeconds(measured.ms)} giây · ${measured.tok.toLocaleString('vi-VN')} token` : 'Ba tác tử viết lần lượt, rồi kiểm tra độ phủ từng ý'}</small></header>
  <ol className="dz-steps dg-steps">{ORDER.map(k => (
            <li key={k} className={`is-${steps[k].state}`}>
              {icon(steps[k])}<b>{STEP_LABEL[k]}</b>
              <span>{steps[k].m ? `${fmtSeconds(steps[k].m!.latency_ms)} giây · ${(steps[k].m!.input_tokens + steps[k].m!.output_tokens).toLocaleString('vi-VN')} token` : steps[k].state === 'run' ? 'Đang chạy…' : ''}
                {steps[k].evidence != null && ` · ${steps[k].evidence} đoạn tài liệu`}{steps[k].shared ? ` (${steps[k].shared} trùng với tác tử trước)` : ''}{steps[k].info ? ` · ${steps[k].info}` : ''}</span>
            </li>
          ))}</ol>
        </section>

        {done && <DistributionBar segments={[
          { label: 'Ý đã bao phủ', value: cnt('COVERED'), tone: 'ok' }, { label: 'Bao phủ một phần', value: cnt('PARTIAL'), tone: 'warn' }, { label: 'Chưa có', value: cnt('MISSING'), tone: 'bad' },
        ]} meta={<>{shared} đoạn trùng giữa các tác tử · {measured.tok.toLocaleString('vi-VN')} token · {fmtSeconds(measured.ms)} giây</>} />}

        {points.length > 0 && <>
          <div className="tabs" role="tablist" aria-label="Phần của gói thiết kế">
            {(['overview', ...DOMAINS, 'export'] as const).map(k => (
              <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'is-on' : ''} onClick={() => setTab(k)} disabled={k !== 'overview' && k !== 'export' && !sections[k as DesignDomain]}>
                {k === 'overview' ? 'Tổng quan' : k === 'export' ? 'Bản nháp xuất' : DOMAIN_VI[k as DesignDomain]}
              </button>
            ))}
          </div>

          {tab === 'overview' && <div className="tbl"><table>
            <thead><tr><th>Ý</th><th>Nội dung</th><th>Chuyên môn</th><th>Độ phủ</th><th>Ghi chú</th></tr></thead>
            <tbody>{points.map(p => { const c = coverage.find(x => x.point_id === p.id); return (
              <tr key={p.id}><td><b>{p.id}</b></td><td className="tv-title">{p.text}</td><td><small>{DOMAIN_VI[p.domain]}</small></td>
                <td>{c ? <span className={`cht-status is-${COVER[c.status].tone}`}>{COVER[c.status].label}</span> : <span className="is-muted">{running ? 'Đang chờ' : '—'}</span>}</td>
                <td><small>{c ? `${c.sections.map(s => DOMAIN_VI[s]).join(', ')}${c.sections.length ? ' · ' : ''}${c.note}` : ''}</small></td></tr>); })}</tbody>
          </table></div>}

          {tab === 'database' && db && <div className="dz-grid">
            {db.tables.length === 0 && <div className="empty">Tác tử không đề xuất bảng nào.</div>}
            {db.tables.map((t: any) => <article key={t.name} className="dz-card">
              <header><h3><code>{t.name}</code></h3><Grounded item={t} onShow={viewer.show} sources={sources} /></header>
              <p>{t.purpose}</p>
              <div className="tbl"><table><thead><tr><th>Cột</th><th>Kiểu</th><th>Ràng buộc</th></tr></thead>
                <tbody>{t.columns.map((c: any) => <tr key={c.name}><td><code>{c.name}</code></td><td><small>{c.type}</small></td><td><small>{c.constraints}</small></td></tr>)}</tbody></table></div>
            </article>)}
            {db.indexes.length > 0 && <article className="dz-card"><header><h3><ListTree size={16} />Chỉ mục</h3></header><ul>{db.indexes.map((i: any, n: number) => <li key={n}><code>{i.table}({i.columns})</code> {i.purpose}</li>)}</ul></article>}
            {db.notes.length > 0 && <article className="dz-card"><header><h3><StickyNote size={16} />Ghi chú thiết kế</h3></header><ul>{db.notes.map((x: any, n: number) => <li key={n}>{x.text} <Grounded item={x} onShow={viewer.show} sources={sources} /></li>)}</ul></article>}
          </div>}

          {tab === 'api_architecture' && api && <div className="dz-grid">
            {api.endpoints.length === 0 && <div className="empty">Tác tử không đề xuất API nào.</div>}
            {api.endpoints.map((e: any, n: number) => <article key={n} className="dz-card">
              <header><h3><span className={`dz-method is-${e.method.toLowerCase()}`}>{e.method}</span><code>{e.path}</code></h3><Grounded item={e} onShow={viewer.show} sources={sources} /></header>
              <p>{e.purpose}</p>
              {e.request.length > 0 && <><b className="dz-sub">Trường vào</b><ul>{e.request.map((x: string, i: number) => <li key={i}><code>{x}</code></li>)}</ul></>}
              {e.responses.length > 0 && <><b className="dz-sub">Phản hồi</b><ul>{e.responses.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></>}
            </article>)}
            {api.notes.length > 0 && <article className="dz-card"><header><h3><StickyNote size={16} />Ghi chú tích hợp</h3></header><ul>{api.notes.map((x: any, n: number) => <li key={n}>{x.text} <Grounded item={x} onShow={viewer.show} sources={sources} /></li>)}</ul></article>}
          </div>}

          {tab === 'security' && sec && <div className="dz-grid">
            {sec.controls.length > 0 && <div className="tbl"><table><thead><tr><th>Rủi ro</th><th>Biện pháp</th><th>Nguồn</th></tr></thead>
              <tbody>{sec.controls.map((c: any, n: number) => <tr key={n}><td>{c.risk}</td><td>{c.control}</td><td><Grounded item={c} onShow={viewer.show} sources={sources} /></td></tr>)}</tbody></table></div>}
            {sec.permissions.length > 0 && <article className="dz-card"><header><h3><KeyRound size={16} />Phân quyền</h3></header><ul>{sec.permissions.map((p: any, n: number) => <li key={n}><b>{p.role}:</b> {p.actions.join('; ')}</li>)}</ul></article>}
            {sec.notes.length > 0 && <article className="dz-card"><header><h3><StickyNote size={16} />Ghi chú bảo mật</h3></header><ul>{sec.notes.map((x: any, n: number) => <li key={n}>{x.text} <Grounded item={x} onShow={viewer.show} sources={sources} /></li>)}</ul></article>}
            {sec.controls.length === 0 && sec.permissions.length === 0 && <div className="empty">Tác tử không đề xuất biện pháp bảo mật nào.</div>}
          </div>}

          {tab === 'export' && <div className="dz-grid">
            {[['sql', 'SQL (PostgreSQL)', sections.database?.sql], ['openapi', 'OpenAPI 3.0', sections.api_architecture?.openapi]].map(([k, label, code]) => code ? (
              <article key={k} className="dz-card"><header><h3>{label}</h3>
                <span className="dz-tools"><button className="btn btn-ghost" onClick={() => copy(k!, code)}><Copy size={14} />{copied === k ? 'Đã chép' : 'Chép'}</button>
                  <button className="btn btn-ghost" onClick={() => download(`${fileBase}.${k === 'sql' ? 'sql' : 'yaml'}`, code, 'text/plain;charset=utf-8')}><Download size={14} />Tải tệp</button></span></header>
                <pre className="dz-code">{code}</pre></article>) : null)}
            <p className="muted-line">Bản nháp do tác tử sinh ra, đã chuẩn hóa cú pháp; kỹ sư cần rà soát trước khi dùng.</p>
          </div>}

          {done && !running && <div className="tv-actions is-end">
            <button className="btn btn-ghost" onClick={() => download(`${fileBase}.md`, markdown(), 'text/markdown;charset=utf-8')}><Download size={15} />Xuất Markdown</button>
            <button className="btn btn-dark" onClick={save}><Save size={15} />Lưu gói thiết kế</button>
          </div>}
        </>}

        {points.length === 0 && !running && <EmptyState Icon={PencilRuler} title="Bắt đầu từ một yêu cầu tính năng"
          text="Nhập yêu cầu (hoặc chọn một ví dụ), chọn tài liệu tham chiếu rồi bấm Tạo gói thiết kế. Cả quy trình chạy cục bộ, thường dưới một phút." />}
      </div>
      {viewer.modal}
    </main>
  );
};
