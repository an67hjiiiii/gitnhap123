// Trang danh mục kiểm tra dùng chung: truy vết yêu cầu (trích từ tài liệu đặc tả) và rà soát bảo mật (bộ tiêu chí OWASP ASVS).
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, CheckCircle2, ChevronDown, ChevronRight, Columns3, Cpu, Download, Files, FileSearch, LayoutGrid, ListChecks, Quote, Rows3, Save, Search, Shield, ShieldAlert, ShieldCheck, Square, Trash2, UserCheck, X } from 'lucide-react';
import { ProfilePreview, useProfileMotion } from './profile/ProfileParts';
import './profile/profile.css';
import './profile/tools.css';
import {
  checkRequirement, deleteReport, extractRequirements, getReport, getSecurityControls, saveReport, TraceRequirement, TraceResult, TraceStatus,
} from '../services/api';
import { baseName, chunkLabel, csvCell, Doc, DocPicker, docId, download, fmtSeconds, SavedReportsSelect, ToolHeader, useAnalysisData, useChunkViewer } from './analysis/shared';

export type ChecklistMode = 'traceability' | 'security';
type Final = TraceStatus | 'ERROR';

const MODES = {
  traceability: {
    kind: 'traceability', title: 'Truy vết yêu cầu', file: 'truy-vet', item: 'yêu cầu', agent: undefined as string | undefined,
    desc: 'Kiểm tra từng yêu cầu trong tài liệu đặc tả đã được tài liệu thiết kế đáp ứng chưa, có trích dẫn.',
    docs: 'Tài liệu thiết kế để đối chiếu', points: 'Đã có trong thiết kế',
    labels: { COVERED: 'Đã đáp ứng', PARTIAL: 'Một phần', MISSING: 'Chưa có trong thiết kế', ERROR: 'Lỗi khi kiểm tra' },
    empty: 'Chọn tài liệu đặc tả rồi bấm "Trích yêu cầu". Hệ thống nhận các dòng bắt đầu bằng mã như FR-01, NFR-02, UC-03.',
  },
  security: {
    kind: 'security_review', title: 'Rà soát bảo mật', file: 'ra-soat-bao-mat', item: 'tiêu chí', agent: 'security' as string | undefined,
    desc: 'Đối chiếu tài liệu thiết kế với danh mục tiêu chí chọn lọc từ OWASP ASVS; mỗi kết luận có trích dẫn để kiểm chứng.',
    docs: 'Tài liệu cần rà soát', points: 'Biện pháp đã có',
    labels: { COVERED: 'Đạt', PARTIAL: 'Đạt một phần', MISSING: 'Chưa thấy biện pháp', ERROR: 'Lỗi khi kiểm tra' },
    empty: 'Đang nạp danh mục tiêu chí…',
  },
} as const;
const TONE: Record<Final, string> = { COVERED: 'complete', PARTIAL: 'partial', MISSING: 'failed', ERROR: 'failed' };
const REQ_DOC = /yeu.?cau|srs|requirement|dac.?ta.?yeu/i;

export const ChecklistView: React.FC<{ mode: ChecklistMode; workspaceId: number | string; docs: Doc[] }> = ({ mode, workspaceId, docs }) => {
  const M = MODES[mode];
  const L = M.labels;
  const flagText = (f: string) => ({
    no_evidence: 'Không tìm thấy đoạn nào liên quan trong tài liệu.',
    no_valid_citation: `Mô hình kết luận "${L.COVERED}" nhưng không trích được căn cứ hợp lệ nên hạ xuống "${L.PARTIAL}".`,
    has_missing_points: `Mô hình còn liệt kê điểm chưa đáp ứng nên hạ xuống "${L.PARTIAL}".`,
    numbers_not_in_evidence: `Con số mục tiêu không có trong đoạn được trích nên hạ xuống "${L.PARTIAL}".`,
    invalid_model_output: 'Mô hình trả kết quả không hợp lệ.',
    invalid_citation_removed: 'Đã bỏ trích dẫn không nằm trong các đoạn được cung cấp.',
    terms_not_in_evidence: `Đoạn được trích không nhắc tới thuật ngữ cốt lõi của tiêu chí nên hạ xuống "${L.PARTIAL}".`,
  } as Record<string, string>)[f] ?? f;

  const { allDocs, saved, setSaved, refreshSaved } = useAnalysisData(M.kind);
  const viewer = useChunkViewer();
  const [sourceId, setSourceId] = useState('');
  const [sourceName, setSourceName] = useState('');
  const [standard, setStandard] = useState('');
  const [design, setDesign] = useState<Set<string>>(new Set());
  const [reqs, setReqs] = useState<TraceRequirement[]>([]);
  const [results, setResults] = useState<Record<string, TraceResult>>({});
  const [review, setReview] = useState<Record<string, TraceStatus>>({});
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | Final>('all');
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const stop = useRef(false);
  const [docsOpen, setDocsOpen] = useState(false);
  const [view, setView] = useState<'board' | 'table'>('board');
  const [group, setGroup] = useState('');

  // Mặc định: truy vết lấy tài liệu giống đặc tả làm nguồn, phần còn lại làm tài liệu thiết kế; rà soát lấy mọi tài liệu của không gian.
  useEffect(() => {
    if (design.size || docs.length === 0) return;
    if (mode === 'security') { setDesign(new Set(docs.map(docId))); return; }
    const first = docs.find(d => REQ_DOC.test(d.source_file)) ?? docs[0];
    setSourceId(docId(first));
    setDesign(new Set(docs.filter(d => d !== first).map(docId)));
  }, [docs, mode]);
  useEffect(() => {
    if (mode !== 'security') return;
    getSecurityControls().then(r => { setReqs(r.controls); setStandard(r.standard); }).catch(e => setError(e.message));
  }, [mode]);

  const pickable = allDocs.length ? allDocs : docs;
  const finalOf = (id: string): Final | undefined => review[id] ?? results[id]?.status;
  const checked = reqs.filter(r => results[r.req_id]);
  const count = (s: Final) => checked.filter(r => finalOf(r.req_id) === s).length;
  const pct = (n: number) => (checked.length ? Math.round((n / checked.length) * 100) : 0);
  const tokens = checked.reduce((n, r) => n + (results[r.req_id].input_tokens || 0) + (results[r.req_id].output_tokens || 0), 0);
  const ms = checked.reduce((n, r) => n + (results[r.req_id].latency_ms || 0), 0);
  const designIds = [...design].filter(id => id && id !== sourceId);
  const subject = mode === 'security' ? standard : sourceName;
  // Mã đoạn mô hình chép vào lời nhận xét ("src_ab12_c0004") đổi thành tên tài liệu và số đoạn.
  const readable = (text: string) => text.replace(/\(?(?:chunk(?:_id)?:?\s*)?\[?(src_[0-9a-f]+)_c(\d+)\]?\)?/gi, (_m, src: string, n: string) =>
    `(${chunkLabel(`${src}_c${n}`, pickable.find(d => docId(d) === src)?.source_file)})`);

  const shown = useMemo(() => reqs.filter(r =>
    (filter === 'all' || finalOf(r.req_id) === filter) && (!group || r.group === group) &&
    (!query.trim() || `${r.req_id} ${r.group ?? ''} ${r.title} ${r.body}`.toLowerCase().includes(query.toLowerCase()))
  ), [reqs, filter, query, results, review, group]);

  const extract = async () => {
    if (!sourceId) return;
    setBusy(true); setError(null); setNote(null);
    try {
      const r = await extractRequirements(sourceId);
      setReqs(r.requirements); setSourceName(r.source_name); setResults({}); setReview({}); setOpen(null);
      if (r.requirements.length === 0) setError('Không tìm thấy yêu cầu có mã (FR-, NFR-, UC-, REQ-…) ở đầu dòng trong tài liệu này.');
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const run = async (onlyPending: boolean) => {
    if (!designIds.length) { setError(`Chọn ít nhất một tài liệu trong mục "${M.docs}".`); return; }
    stop.current = false; setRunning(true); setError(null); setNote(null);
    for (const r of reqs) {
      if (stop.current) break;
      if (onlyPending && results[r.req_id] && results[r.req_id].status !== 'ERROR') continue;
      try {
        const res = await checkRequirement(r, designIds, M.agent);
        setResults(prev => ({ ...prev, [r.req_id]: res }));
      } catch (e: any) {
        setResults(prev => ({ ...prev, [r.req_id]: { req_id: r.req_id, status: 'ERROR', agent: r.agent, agent_name: r.agent_name, citations: [], evidence: [], covered_points: [], missing_points: [], note: e.message, flags: [], input_tokens: 0, output_tokens: 0, latency_ms: 0 } }));
      }
    }
    setRunning(false);
  };

  const summary = () => ({ total: reqs.length, checked: checked.length, covered: count('COVERED'), partial: count('PARTIAL'), missing: count('MISSING'), errors: count('ERROR'), reviewed: Object.keys(review).length, tokens, seconds: ms / 1000 });
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await saveReport({ kind: M.kind, title: `${M.title} ${subject} · ${new Date().toLocaleString('vi-VN')}`, workspace_id: typeof workspaceId === 'string' && workspaceId ? workspaceId : null,
        payload: { source_id: sourceId, source_name: sourceName, standard, design_ids: designIds, requirements: reqs, results, review, summary: summary() } });
      await refreshSaved(); setNote('Đã lưu báo cáo.');
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const load = async (id: string) => {
    setBusy(true); setError(null); setNote(null);
    try {
      const p = (await getReport(id)).payload;
      setSourceId(p.source_id ?? ''); setSourceName(p.source_name ?? ''); setStandard(p.standard ?? ''); setDesign(new Set(p.design_ids));
      setReqs(p.requirements); setResults(p.results); setReview(p.review || {}); setOpen(null);
      setNote('Đã mở báo cáo đã lưu.');
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const remove = async (id: string) => {
    if (!window.confirm('Xóa báo cáo đã lưu này?')) return;
    try { await deleteReport(id); setSaved(s => s.filter(x => x.report_id !== id)); } catch (e: any) { setError(e.message); }
  };

  const rows = () => reqs.map(r => {
    const res = results[r.req_id]; const fin = finalOf(r.req_id);
    return { id: r.req_id, group: r.group ?? '', title: r.title, agent: res?.agent_name ?? r.agent_name, model: res ? L[res.status] : 'Chưa kiểm tra',
      final: fin ? L[fin] : 'Chưa kiểm tra', reviewed: review[r.req_id] ? 'Có' : 'Không',
      evidence: (res?.citations ?? []).map(c => chunkLabel(c, res!.evidence.find(e => e.chunk_id === c)?.source_name)).join('; '),
      missing: (res?.missing_points ?? []).map(readable).join('; '), note: readable(res?.note ?? '') };
  });
  const fileName = (ext: string) => `${M.file}-${baseName(subject || 'bao-cao').replace(/\s+/g, '-')}.${ext}`;
  const exportCsv = () => {
    const head = ['Mã', ...(mode === 'security' ? ['Nhóm'] : []), M.item === 'tiêu chí' ? 'Tiêu chí' : 'Yêu cầu', 'Tác tử', 'Kết luận mô hình', 'Kết luận cuối', 'Đã duyệt', 'Căn cứ', 'Điểm còn thiếu', 'Ghi chú'];
    const body = rows().map(x => [x.id, ...(mode === 'security' ? [x.group] : []), x.title, x.agent, x.model, x.final, x.reviewed, x.evidence, x.missing, x.note].map(csvCell).join(','));
    download(fileName('csv'), '﻿' + [head.map(csvCell).join(','), ...body].join('\r\n'), 'text/csv;charset=utf-8');
  };
  const exportMd = () => {
    const s = summary();
    const lines = [`# Báo cáo ${M.title.toLowerCase()}`, '',
      mode === 'security' ? `- Danh mục: ${standard} (chọn lọc ${reqs.length} tiêu chí; không thay thế đánh giá chứng nhận)` : `- Tài liệu yêu cầu: ${sourceName}`,
      `- ${M.docs}: ${designIds.map(id => pickable.find(d => docId(d) === id)?.source_file ?? id).join(', ')}`,
      `- Đã kiểm tra: ${s.checked}/${s.total} · ${L.COVERED} ${s.covered} · ${L.PARTIAL} ${s.partial} · ${L.MISSING} ${s.missing} · Lỗi ${s.errors} · Đã duyệt ${s.reviewed}`,
      `- Kết luận do mô hình cục bộ đưa ra kèm trích dẫn; dòng "Đã duyệt = Có" đã được người dùng xác nhận hoặc sửa.`, '',
      `| Mã |${mode === 'security' ? ' Nhóm |' : ''} ${M.item === 'tiêu chí' ? 'Tiêu chí' : 'Yêu cầu'} | Kết luận cuối | Đã duyệt | Căn cứ | Điểm còn thiếu |`,
      `|---|${mode === 'security' ? '---|' : ''}---|---|---|---|---|`,
      ...rows().map(x => `| ${x.id} |${mode === 'security' ? ` ${x.group} |` : ''} ${x.title.replace(/\|/g, '/')} | ${x.final} | ${x.reviewed} | ${x.evidence} | ${x.missing.replace(/\|/g, '/')} |`)];
    download(fileName('md'), lines.join('\n'), 'text/markdown;charset=utf-8');
  };

  const pfRef = useRef<HTMLDivElement>(null);
  useProfileMotion(pfRef, `${mode}|${reqs.length}|${checked.length > 0}|${view}`, '.wb-in');
  const openRow = (id: string) => { setView('table'); setFilter('all'); setQuery(''); setGroup(''); setOpen(id); requestAnimationFrame(() => document.getElementById(`tv-row-${id}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })); };
  const progress = reqs.length ? Math.round((checked.length / reqs.length) * 100) : 0;
  const errors = count('ERROR');
  const allChecked = reqs.length > 0 && checked.length === reqs.length;

  return (
    <main className={`pg tl tone-${mode === 'security' ? 'security' : 'trace'}`}>
      <div className="pg-col tv-col">
        <ToolHeader Icon={mode === 'security' ? ShieldCheck : ListChecks} title={M.title} desc={M.desc}
          right={<SavedReportsSelect saved={saved} onLoad={load} disabled={running || busy} />} />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span><button className="note-x" onClick={() => setError(null)} aria-label="Đóng thông báo"><X size={14} /></button></div>}
        {note && <p className="muted-line" role="status"><CheckCircle2 size={14} />{note}</p>}

        <div className="wb" ref={pfRef}>
          {/* Thanh thiết lập: nguồn → đối chiếu → chạy, gọn trên một hàng */}
          <section className="wb-bar wb-in">
            <div className="wb-slot">
              <span className="wb-k">{mode === 'security' ? 'Danh mục' : 'Đặc tả'}</span>
              {mode === 'traceability'
                ? <label className="wb-select"><span className="sr">Tài liệu yêu cầu (đặc tả)</span>
                    <select value={sourceId} onChange={e => { setSourceId(e.target.value); setReqs([]); setResults({}); setReview({}); }} disabled={running}>
                      <option value="">Chọn tài liệu đặc tả…</option>
                      {pickable.map(d => <option key={docId(d)} value={docId(d)}>{d.source_file.replace(/\.[^.]+$/, '').replace(/_/g, ' ')}</option>)}
                    </select><ChevronDown size={16} aria-hidden="true" /></label>
                : <b className="wb-v">{standard || 'Đang nạp…'}<small>{reqs.length} tiêu chí</small></b>}
            </div>
            <ArrowRight className="wb-arrow" size={18} aria-hidden="true" />
            <div className="wb-slot">
              <span className="wb-k">{mode === 'security' ? 'Tài liệu rà soát' : 'Đối chiếu với'}</span>
              <button type="button" className={`wb-pick${docsOpen ? ' is-open' : ''}`} onClick={() => setDocsOpen(v => !v)} aria-expanded={docsOpen} disabled={running}>
                <Files size={15} /><b>{designIds.length}</b> tài liệu<ChevronDown size={15} />
              </button>
            </div>
            <div className="wb-go">
              {mode === 'traceability' && <button className={`btn ${reqs.length ? 'btn-ghost' : 'btn-dark'}`} onClick={extract} disabled={!sourceId || running || busy}><FileSearch size={15} />{reqs.length ? 'Trích lại' : 'Trích yêu cầu'}</button>}
              {reqs.length > 0 && (running
                ? <button className="btn btn-danger" onClick={() => { stop.current = true; }}><Square size={14} />Dừng</button>
                : <button className="btn btn-dark" onClick={() => run(checked.length > 0)} disabled={busy}><ListChecks size={15} />
                    {checked.length === 0 ? `Kiểm tra ${reqs.length} ${M.item}` : checked.length < reqs.length || errors ? `Kiểm tra tiếp ${reqs.length - checked.length + errors}` : 'Kiểm tra lại'}
                  </button>)}
            </div>
            {docsOpen && <div className="wb-drop"><DocPicker docs={pickable} selected={design} onChange={setDesign} exclude={sourceId} disabled={running} legend={M.docs} /></div>}
            {reqs.length > 0 && <div className="wb-progress" aria-label={`Đã kiểm tra ${checked.length}/${reqs.length}`}>
              <i style={{ width: `${progress}%` }} /><span>{running && <span className="spin is-dark" />}Đã kiểm tra <b>{checked.length}/{reqs.length}</b>{checked.length > 0 && <> · {tokens.toLocaleString('vi-VN')} token · {fmtSeconds(ms)} giây</>}</span>
            </div>}
          </section>

          {/* Truy vết: bảng Kanban theo kết luận. Bảo mật: lưới nhóm tiêu chí. */}
          {mode === 'traceability' && reqs.length > 0 && view === 'board' && <div className="kb">
            {(['MISSING', 'PARTIAL', 'COVERED', ...(errors ? ['ERROR'] : []), ...(checked.length < reqs.length ? ['TODO'] : [])] as (Final | 'TODO')[]).map(col => {
              const list = reqs.filter(r => (finalOf(r.req_id) ?? 'TODO') === col);
              return (
                <section key={col} className={`kb-col is-${col.toLowerCase()} wb-in`}>
                  <header><i /><h3>{col === 'TODO' ? 'Chưa kiểm tra' : L[col]}</h3><b>{list.length}</b>{checked.length > 0 && col !== 'TODO' && <em>{pct(list.length)}%</em>}</header>
                  <div className="kb-cards">{list.length === 0 ? <p className="kb-none">Không có</p> : list.map(r => {
                    const res = results[r.req_id];
                    return <button key={r.req_id} type="button" className="kb-card" onClick={() => openRow(r.req_id)}>
                      <span className="kb-top"><b>{r.req_id}</b>{review[r.req_id] && <span className="kb-rv"><UserCheck size={12} />đã duyệt</span>}</span>
                      <span className="kb-title">{r.title}</span>
                      <span className="kb-meta">{(res?.agent_name ?? r.agent_name).replace(' Analyst', '')}{res && <> · {res.citations.length} căn cứ</>}</span>
                    </button>;
                  })}</div>
                </section>
              );
            })}
          </div>}

          {mode === 'security' && reqs.length > 0 && <div className="sg">
            {Object.entries(reqs.reduce((g, r) => { (g[r.group ?? 'Khác'] ??= []).push(r); return g; }, {} as Record<string, TraceRequirement[]>)).map(([g, list]) => {
              const n = (st: Final) => list.filter(r => finalOf(r.req_id) === st).length;
              const done = list.filter(r => finalOf(r.req_id)).length;
              const tone = n('MISSING') ? 'bad' : n('PARTIAL') ? 'warn' : done === list.length && done ? 'ok' : 'todo';
              return (
                <button key={g} type="button" className={`sg-card is-${tone}${group === g ? ' is-on' : ''} wb-in`} onClick={() => setGroup(group === g ? '' : g)} aria-pressed={group === g}>
                  <span className="sg-ico">{tone === 'ok' ? <ShieldCheck size={22} /> : tone === 'todo' ? <Shield size={22} /> : <ShieldAlert size={22} />}</span>
                  <span className="sg-name">{g}</span>
                  <span className="sg-count"><b>{n('COVERED')}</b>/{list.length} {L.COVERED.toLowerCase()}</span>
                  <span className="sg-bar">{(['COVERED', 'PARTIAL', 'MISSING'] as Final[]).map(st => n(st) > 0 && <i key={st} className={`is-${st.toLowerCase()}`} style={{ flexGrow: n(st) }} />)}{done < list.length && <i className="is-todo" style={{ flexGrow: list.length - done }} />}</span>
                  <span className="sg-ids">{list.map(r => r.req_id).join(' · ')}</span>
                </button>
              );
            })}
          </div>}
        </div>

        {checked.length > 0 && <>
          <div className="row-head">
            <div className="seg tv-seg">{(['all', 'COVERED', 'PARTIAL', 'MISSING', 'ERROR'] as const).map(k => (
              <button key={k} className={filter === k ? 'is-on' : ''} aria-pressed={filter === k} onClick={() => setFilter(k)}>{k === 'all' ? 'Tất cả' : L[k]}</button>
            ))}</div>
            {mode === 'traceability' && <div className="seg tv-seg wb-view" role="group" aria-label="Kiểu xem">
              <button className={view === 'board' ? 'is-on' : ''} aria-pressed={view === 'board'} onClick={() => setView('board')}><Columns3 size={14} />Bảng Kanban</button>
              <button className={view === 'table' ? 'is-on' : ''} aria-pressed={view === 'table'} onClick={() => setView('table')}><Rows3 size={14} />Bảng chi tiết</button>
            </div>}
            {group && <button className="chip is-on" onClick={() => setGroup('')}>Nhóm: {group} ✕</button>}
            <label className="search"><Search size={14} /><span className="sr">Tìm {M.item}</span><input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Tìm mã hoặc nội dung" /></label>
          </div>
        </>}

        {reqs.length > 0 && (mode === 'security' || view === 'table' || checked.length === 0) && <div className="tbl tv-table">
          <table>
            <thead><tr><th>Mã</th><th>{mode === 'security' ? 'Tiêu chí' : 'Yêu cầu'}</th><th>{mode === 'security' ? 'Nhóm' : 'Tác tử'}</th><th>Kết luận</th><th>Người duyệt</th><th>Căn cứ</th></tr></thead>
            <tbody>{shown.map(r => {
              const res = results[r.req_id]; const fin = finalOf(r.req_id); const isOpen = open === r.req_id;
              return (
                <React.Fragment key={r.req_id}>
                  <tr id={`tv-row-${r.req_id}`} className={isOpen ? 'is-open' : ''}>
                    <td><button className="tv-expand" onClick={() => setOpen(isOpen ? null : r.req_id)} aria-expanded={isOpen} aria-label={`Chi tiết ${r.req_id}`}>{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<b>{r.req_id}</b></button></td>
                    <td className="tv-title">{r.title}</td>
                    <td><small>{mode === 'security' ? r.group : (res?.agent_name ?? r.agent_name).replace(' Analyst', '')}</small></td>
                    <td>{res ? <span className={`cht-status is-${TONE[res.status]}`}>{L[res.status]}</span> : <span className="is-muted">{running ? 'Đang chờ' : 'Chưa kiểm tra'}</span>}</td>
                    <td>{res && res.status !== 'ERROR' && (
                      <select aria-label={`Kết luận của người duyệt cho ${r.req_id}`} value={review[r.req_id] ?? ''} onChange={e => setReview(prev => { const n = { ...prev }; if (e.target.value) n[r.req_id] = e.target.value as TraceStatus; else delete n[r.req_id]; return n; })}>
                        <option value="">Chưa duyệt</option>
                        <option value="COVERED">{L.COVERED}</option>
                        <option value="PARTIAL">{L.PARTIAL}</option>
                        <option value="MISSING">{L.MISSING}</option>
                      </select>)}
                      {fin && review[r.req_id] && review[r.req_id] !== res?.status && <small className="tv-changed">đã sửa</small>}
                    </td>
                    <td>{res && res.citations.length > 0
                      ? <button className="tv-cite-count" onClick={() => setOpen(isOpen ? null : r.req_id)} aria-expanded={isOpen}>{res.citations.length} đoạn</button>
                      : res && <span className="is-muted">Không có</span>}</td>
                  </tr>
                  {isOpen && <tr className="tv-detail"><td colSpan={6}>
                    {r.body && <p className="tv-body">{r.body}</p>}
                    {res ? <div className="tv-points">
                      {res.note && <p><b>Nhận xét:</b> {readable(res.note)}</p>}
                      {res.covered_points.length > 0 && <div><b>{M.points}</b><ul>{res.covered_points.map((p, i) => <li key={i}>{readable(p)}</li>)}</ul></div>}
                      {res.missing_points.length > 0 && <div><b>Còn thiếu</b><ul>{res.missing_points.map((p, i) => <li key={i}>{readable(p)}</li>)}</ul></div>}
                      {res.flags.map(f => <p key={f} className="tv-flag"><AlertCircle size={13} />{flagText(f)}</p>)}
                      {res.citations.length > 0 && <p className="tv-ev"><b>Căn cứ được trích:</b> {res.citations.map(c => <button key={c} onClick={() => viewer.show(c)}>{chunkLabel(c, res.evidence.find(e => e.chunk_id === c)?.source_name)}</button>)}</p>}
                      {res.evidence.length > 0 && <p className="tv-ev"><b>Đoạn đã đọc:</b> {res.evidence.map(e => <button key={e.chunk_id} onClick={() => viewer.show(e.chunk_id)}>{chunkLabel(e.chunk_id, e.source_name)}</button>)}</p>}
                      <p className="is-muted">{res.agent_name} · {(res.input_tokens + res.output_tokens).toLocaleString('vi-VN')} token · {fmtSeconds(res.latency_ms)} giây</p>
                    </div> : <p className="is-muted">Chưa kiểm tra.</p>}
                  </td></tr>}
                </React.Fragment>
              );
            })}</tbody>
          </table>
          {shown.length === 0 && <div className="empty">Không có {M.item} phù hợp bộ lọc.</div>}
        </div>}

        {reqs.length === 0 && !busy && <ProfilePreview title={mode === 'security' ? 'Kết quả rà soát sẽ có' : 'Kết quả truy vết sẽ có'}
          text={mode === 'security' ? 'Chọn tài liệu cần rà soát rồi bấm Kiểm tra. Mỗi tiêu chí do tác tử bảo mật đối chiếu, kèm đoạn tài liệu làm căn cứ.' : 'Chọn tài liệu đặc tả, bấm Trích yêu cầu rồi Kiểm tra. Mỗi yêu cầu do một tác tử đối chiếu với tài liệu thiết kế.'}
          items={[[LayoutGrid, 'Bản đồ độ phủ', 'Thấy ngay yêu cầu nào thiết kế còn thiếu'], [ListChecks, 'Bảng từng mục', 'Đã đáp ứng, một phần hoặc chưa có'], [Quote, 'Căn cứ trích dẫn', 'Bấm để mở đúng đoạn tài liệu gốc'],
            [UserCheck, 'Người duyệt', 'Sửa kết luận của mô hình trước khi xuất'], [Download, 'Xuất báo cáo', 'CSV, Markdown, lưu để mở lại'], [Cpu, 'Đo thật', 'Token và thời gian của từng lần kiểm tra']]} />}

        {checked.length > 0 && !running && <div className="tv-actions is-end">
          <button className="btn btn-ghost" onClick={exportCsv}><Download size={15} />Xuất CSV</button>
          <button className="btn btn-ghost" onClick={exportMd}><Download size={15} />Xuất Markdown</button>
          <button className="btn btn-dark" onClick={save} disabled={busy}><Save size={15} />Lưu báo cáo</button>
        </div>}

        {saved.length > 0 && <details className="tv-saved-list"><summary>Báo cáo đã lưu ({saved.length})</summary>
          <ul>{saved.map(s => <li key={s.report_id}><button onClick={() => void load(s.report_id)}>{s.title}</button><button className="icon-btn is-sm" aria-label={`Xóa ${s.title}`} onClick={() => void remove(s.report_id)}><Trash2 size={14} /></button></li>)}</ul>
        </details>}
      </div>
      {viewer.modal}
    </main>
  );
};
