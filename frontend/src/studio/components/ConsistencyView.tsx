// Kiểm tra mâu thuẫn giữa các tài liệu: tìm cặp câu nghi vấn (không dùng mô hình) rồi để tác tử xét từng cặp.
import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, Bot, ChevronDown, Files, Grid3x3, CheckCircle2, Cpu, Download, GitCompareArrows, HelpCircle, Quote, Save, Search, Square, UserCheck, X, XCircle } from 'lucide-react';
import { ProfilePreview, useProfileMotion } from './profile/ProfileParts';
import './profile/profile.css';
import './profile/tools.css';
import { ConsistencyPair, ConsistencyVerdict, consistencyCandidates, consistencyJudge, getReport, canSaveReports, saveReport } from '../services/api';
import { chunkLabel, csvCell, Doc, DocPicker, docId, download, fmtSeconds, SavedReportsSelect, ToolHeader, useAnalysisData, useChunkViewer } from './analysis/shared';

type Verdict = ConsistencyVerdict['verdict'];
const VERDICT: Record<Verdict | 'ERROR', { label: string; tone: string }> = {
  CONTRADICTION: { label: 'Mâu thuẫn', tone: 'failed' }, CONSISTENT: { label: 'Nhất quán', tone: 'complete' }, UNRELATED: { label: 'Chưa xác nhận', tone: 'partial' },
  ERROR: { label: 'Lỗi khi kiểm tra', tone: 'failed' },
};
const SEVERITY: Record<string, string> = { HIGH: 'Cao', MEDIUM: 'Trung bình', LOW: 'Thấp' };
const REASON: Record<string, string> = { numbers_differ: 'Khác con số', negation_differs: 'Khác phủ định' };
const FLAG: Record<string, string> = {
  unverified_values: 'Mô hình báo mâu thuẫn nhưng không chỉ ra được hai giá trị xung đột có thật trong hai câu, nên chưa xác nhận.',
  non_numeric_unverified: 'Mô hình báo mâu thuẫn không dựa trên con số; hệ thống chưa tự xác nhận được, người duyệt cần xem.',
  different_scope: 'Hai con số áp cho phạm vi khác nhau (ví dụ cho mỗi merchant so với toàn hệ thống) nên chưa xác nhận là mâu thuẫn.',
  different_subject: 'Mô hình nhận định hai câu nói về chủ đề khác nhau.',
  superseded: 'Văn bản mới ghi rõ thay thế văn bản cũ: khác nhau là do thay thế hợp lệ, không phải mâu thuẫn (luật cố định).',
  invalid_model_output: 'Mô hình trả kết quả không hợp lệ.',
};
type Result = Omit<Partial<ConsistencyVerdict>, 'verdict'> & { verdict: Verdict | 'ERROR'; error?: string };

export const ConsistencyView: React.FC<{ workspaceId: number | string; docs: Doc[] }> = ({ workspaceId, docs }) => {
  const { allDocs, saved, refreshSaved } = useAnalysisData('consistency');
  const viewer = useChunkViewer();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pairs, setPairs] = useState<ConsistencyPair[]>([]);
  const [statements, setStatements] = useState(0);
  const [results, setResults] = useState<Record<string, Result>>({});
  const [review, setReview] = useState<Record<string, Verdict>>({});
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | Verdict>('all');
  const stop = useRef(false);

  useEffect(() => { if (selected.size === 0 && docs.length) setSelected(new Set(docs.map(docId))); }, [docs]);
  const pickable = allDocs.length ? allDocs : docs;
  const ids = [...selected].filter(Boolean);
  const finalOf = (id: string) => review[id] ?? results[id]?.verdict;
  const checked = pairs.filter(p => results[p.pair_id]);
  const count = (v: Verdict) => checked.filter(p => finalOf(p.pair_id) === v).length;
  const measured = checked.reduce((a, p) => ({ tok: a.tok + (results[p.pair_id].input_tokens ?? 0) + (results[p.pair_id].output_tokens ?? 0), ms: a.ms + (results[p.pair_id].latency_ms ?? 0) }), { tok: 0, ms: 0 });
  const [docsOpen, setDocsOpen] = useState(false);
  const [docPair, setDocPair] = useState('');
  const pairKey = (p: ConsistencyPair) => [p.a.source_id, p.b.source_id].sort().join('|');
  const shown = pairs.filter(p => (filter === 'all' || finalOf(p.pair_id) === filter) && (!docPair || pairKey(p) === docPair.split('|').sort().join('|')));
  // Ma trận tài liệu × tài liệu: số cặp nghi vấn và số mâu thuẫn giữa từng hai tài liệu.
  const matrix = (() => {
    const seen = new Map<string, string>();
    pairs.forEach(p => { seen.set(p.a.source_id, p.a.source_name); seen.set(p.b.source_id, p.b.source_name); });
    const docsM = [...seen].map(([id, name]) => ({ id, name: name.replace(/\.[^.]+$/, '').replace(/_/g, ' ') })).sort((x, y) => x.name.localeCompare(y.name));
    const cells = new Map<string, { n: number; bad: number }>();
    pairs.forEach(p => { const k = pairKey(p); const c = cells.get(k) ?? { n: 0, bad: 0 }; c.n++; if (finalOf(p.pair_id) === 'CONTRADICTION') c.bad++; cells.set(k, c); });
    return { docs: docsM, max: Math.max(1, ...[...cells.values()].map(c => c.n)), cell: (a: string, b: string) => cells.get([a, b].sort().join('|')) ?? { n: 0, bad: 0 } };
  })();

  const find = async () => {
    if (ids.length < 1) { setError('Chọn ít nhất một tài liệu để kiểm tra mâu thuẫn.'); return; }
    setBusy(true); setError(null); setNote(null);
    try {
      const r = await consistencyCandidates(ids, 20);
      setPairs(r.pairs); setStatements(r.statements); setResults({}); setReview({});
      if (!r.pairs.length) setNote(`Đã quét ${r.statements} câu quy định; không có cặp nào cùng chủ đề mà khác con số hoặc khác phủ định.`);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const judge = async (onlyPending: boolean) => {
    stop.current = false; setRunning(true); setError(null); setNote(null);
    for (const p of pairs) {
      if (stop.current) break;
      if (onlyPending && results[p.pair_id] && results[p.pair_id].verdict !== 'ERROR') continue;
      try { const r = await consistencyJudge(p.a, p.b); setResults(prev => ({ ...prev, [p.pair_id]: r })); }
      catch (e: any) { setResults(prev => ({ ...prev, [p.pair_id]: { verdict: 'ERROR', error: e.message } })); }
    }
    setRunning(false);
  };
  const save = async () => {
    try {
      if (canSaveReports()) await saveReport({ kind: 'consistency', title: `Mâu thuẫn tài liệu · ${ids.length} tài liệu · ${new Date().toLocaleString('vi-VN')}`, workspace_id: typeof workspaceId === 'string' && workspaceId ? workspaceId : null,
        payload: { source_ids: ids, statements, pairs, results, review } });
      await refreshSaved(); setNote('Đã lưu báo cáo.');
    } catch (e: any) { setError(e.message); }
  };
  const load = async (id: string) => {
    try { const p = (await getReport(id)).payload; setSelected(new Set(p.source_ids)); setStatements(p.statements); setPairs(p.pairs); setResults(p.results); setReview(p.review || {}); setNote('Đã mở báo cáo đã lưu.'); }
    catch (e: any) { setError(e.message); }
  };
  const rows = () => pairs.map(p => { const r = results[p.pair_id]; const f = finalOf(p.pair_id);
    return [p.pair_id, REASON[p.reason], p.a.source_name, p.a.text, p.b.source_name, p.b.text, r ? VERDICT[r.verdict].label : 'Chưa kiểm tra', f ? VERDICT[f].label : 'Chưa kiểm tra', review[p.pair_id] ? 'Có' : 'Không', r?.severity ? SEVERITY[r.severity] : '', r?.explanation ?? r?.error ?? '']; });
  const exportCsv = () => download('mau-thuan-tai-lieu.csv', '﻿' + [['Cặp', 'Lý do nghi vấn', 'Tài liệu A', 'Nội dung A', 'Tài liệu B', 'Nội dung B', 'Kết luận mô hình', 'Kết luận cuối', 'Đã duyệt', 'Mức độ', 'Giải thích'], ...rows()].map(r => r.map(csvCell).join(',')).join('\r\n'), 'text/csv;charset=utf-8');
  const exportMd = () => download('mau-thuan-tai-lieu.md', [`# Báo cáo kiểm tra mâu thuẫn tài liệu`, '', `- Tài liệu: ${ids.map(id => pickable.find(d => docId(d) === id)?.source_file ?? id).join(', ')}`,
    `- Câu quy định đã quét: ${statements} · Cặp nghi vấn: ${pairs.length} · Mâu thuẫn: ${count('CONTRADICTION')} · Nhất quán: ${count('CONSISTENT')} · Không liên quan: ${count('UNRELATED')}`, '',
    ...pairs.filter(p => finalOf(p.pair_id) === 'CONTRADICTION').flatMap(p => [`## ${p.pair_id} · ${results[p.pair_id]?.severity ? SEVERITY[results[p.pair_id].severity!] : ''}`, `- **${p.a.source_name}:** ${p.a.text}`, `- **${p.b.source_name}:** ${p.b.text}`, `- ${results[p.pair_id]?.explanation ?? ''}`, ''])].join('\n'), 'text/markdown;charset=utf-8');

  const pfRef = useRef<HTMLDivElement>(null);
  useProfileMotion(pfRef, `${pairs.length}|${checked.length > 0}`, '.wb-in');

  return (
    <main className="pg tl tone-consistency">
      <div className="pg-col tv-col">
        <ToolHeader Icon={GitCompareArrows} title="Kiểm tra mâu thuẫn" desc="Tìm những chỗ các tài liệu của dự án nói khác nhau về cùng một quy định (con số, giới hạn, quyền), trước khi chúng thành lỗi trong sản phẩm."
          right={<SavedReportsSelect saved={saved} onLoad={load} disabled={running || busy} />} />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span><button className="note-x" onClick={() => setError(null)} aria-label="Đóng thông báo"><X size={14} /></button></div>}
        {note && <p className="muted-line" role="status"><CheckCircle2 size={14} />{note}</p>}

        <div className="wb" ref={pfRef}>
          <section className="wb-bar wb-in">
            <div className="wb-slot">
              <span className="wb-k">Đối chiếu chéo</span>
              <button type="button" className={`wb-pick${docsOpen ? ' is-open' : ''}`} onClick={() => setDocsOpen(v => !v)} aria-expanded={docsOpen} disabled={running}>
                <Files size={15} /><b>{ids.length}</b> tài liệu<ChevronDown size={15} />
              </button>
            </div>
            <div className="wb-slot">
              <span className="wb-k">Cách làm</span>
              <b className="wb-v">Ghép câu tại máy<small>tác tử chỉ xét các cặp nghi vấn</small></b>
            </div>
            <div className="wb-go">
              <button className={`btn ${pairs.length ? 'btn-ghost' : 'btn-dark'}`} onClick={find} disabled={busy || running || ids.length < 2}><Search size={15} />{pairs.length ? 'Tìm lại' : 'Tìm cặp nghi vấn'}</button>
              {pairs.length > 0 && (running
                ? <button className="btn btn-danger" onClick={() => { stop.current = true; }}><Square size={14} />Dừng</button>
                : <button className="btn btn-dark" onClick={() => judge(checked.length > 0)}><GitCompareArrows size={15} />{checked.length === 0 ? `Xét ${pairs.length} cặp` : checked.length < pairs.length ? `Xét tiếp ${pairs.length - checked.length}` : 'Xét lại'}</button>)}
            </div>
            {docsOpen && <div className="wb-drop"><DocPicker docs={pickable} selected={selected} onChange={setSelected} disabled={running} legend="Tài liệu cần đối chiếu (ít nhất 2)" /></div>}
            {pairs.length > 0 && <div className="wb-progress"><i style={{ width: `${Math.round((checked.length / pairs.length) * 100)}%` }} />
              <span>{running && <span className="spin is-dark" />}Quét <b>{statements}</b> câu quy định · <b>{pairs.length}</b> cặp nghi vấn · đã xét <b>{checked.length}</b>
                {checked.length > 0 && <> · <b className="cs-red">{count('CONTRADICTION')}</b> mâu thuẫn · {measured.tok.toLocaleString('vi-VN')} token</>}</span></div>}
          </section>

          {pairs.length > 0 && matrix.docs.length > 1 && <section className="dz-card mx wb-in">
            <header><h3><Grid3x3 size={16} />Tài liệu nào nói khác tài liệu nào</h3><span className="is-muted">mỗi ô: số cặp nghi vấn{checked.length > 0 && ', chấm đỏ là mâu thuẫn'} · bấm để lọc</span></header>
            <div className="mx-scroll"><table className="mx-t">
              <thead><tr><th />{matrix.docs.map((d, c) => <th key={d.id} scope="col" title={d.name}><span>{c + 1}</span></th>)}</tr></thead>
              <tbody>{matrix.docs.map((rd, r) => <tr key={rd.id}>
                <th scope="row" title={rd.name}><span className="mx-n">{r + 1}</span>{rd.name}</th>
                {matrix.docs.map((cd, c) => {
                  if (c <= r) return <td key={cd.id} className="mx-off" />;
                  const cell = matrix.cell(rd.id, cd.id);
                  const on = docPair === `${rd.id}|${cd.id}`;
                  return <td key={cd.id}>{cell.n ? <button type="button" className={`mx-c${on ? ' is-on' : ''}`} style={{ ['--k' as string]: String(cell.n / matrix.max) }} onClick={() => setDocPair(on ? '' : `${rd.id}|${cd.id}`)} aria-pressed={on}
                    title={`${rd.name} ↔ ${cd.name}: ${cell.n} cặp nghi vấn${cell.bad ? `, ${cell.bad} mâu thuẫn` : ''}`}><b>{cell.n}</b>{cell.bad > 0 && <i>{cell.bad}</i>}</button> : <span className="mx-0">·</span>}</td>;
                })}
              </tr>)}</tbody>
            </table></div>
          </section>}
        </div>

        {checked.length > 0 && <>
          {docPair && <p className="muted-line">Đang xem các cặp giữa <b>{matrix.docs.find(d => d.id === docPair.split('|')[0])?.name}</b> và <b>{matrix.docs.find(d => d.id === docPair.split('|')[1])?.name}</b> · <button className="dp-link" onClick={() => setDocPair('')}>bỏ lọc</button></p>}
          <div className="row-head"><div className="seg tv-seg">{(['all', 'CONTRADICTION', 'CONSISTENT', 'UNRELATED'] as const).map(k => (
            <button key={k} className={filter === k ? 'is-on' : ''} aria-pressed={filter === k} onClick={() => setFilter(k)}>{k === 'all' ? 'Tất cả' : VERDICT[k].label}</button>))}</div></div>
        </>}

        {pairs.length > 0 && <div className="dz-grid">{shown.map(p => { const r = results[p.pair_id]; const f = finalOf(p.pair_id); return (
          <article key={p.pair_id} className={`dz-card cs-pair${f === 'CONTRADICTION' ? ' is-conflict' : ''}`}>
            <header><h3>{p.pair_id} <small className="is-muted">· {REASON[p.reason]} · trùng chủ đề {Math.round(p.overlap * 100)}%</small></h3>
              <span>{r ? <span className={`cht-status is-${VERDICT[r.verdict].tone}`}>{VERDICT[r.verdict].label}{r.severity && r.verdict === 'CONTRADICTION' ? ` · mức ${SEVERITY[r.severity]}` : ''}</span> : <span className="is-muted">{running ? 'Đang chờ' : 'Chưa xét'}</span>}</span></header>
            <div className="cs-sides">
              {[p.a, p.b].map(s => <blockquote key={s.sid}><button className="cs-src" onClick={() => viewer.show(s.chunk_id)} title="Xem đoạn gốc">{chunkLabel(s.chunk_id, s.source_name)}</button><p>{s.text}</p></blockquote>)}
            </div>
            {r?.verdict === 'CONTRADICTION' && r.value_a && <p className="cs-values"><b>Giá trị xung đột:</b> <code>{r.value_a}</code> ↔ <code>{r.value_b}</code></p>}
            {r?.explanation && <p><b>Nhận xét:</b> {r.explanation}</p>}
            {r?.flags?.map(f => <p key={f} className="tv-flag"><AlertCircle size={13} />{FLAG[f] ?? f}</p>)}
            {r?.error && <p className="note is-error">{r.error}</p>}
            {r && r.verdict !== 'ERROR' && <label className="cs-review">Người duyệt:
              <select value={review[p.pair_id] ?? ''} onChange={e => setReview(prev => { const n = { ...prev }; if (e.target.value) n[p.pair_id] = e.target.value as Verdict; else delete n[p.pair_id]; return n; })}>
                <option value="">Chưa duyệt</option><option value="CONTRADICTION">Mâu thuẫn</option><option value="CONSISTENT">Nhất quán</option><option value="UNRELATED">Không liên quan</option>
              </select></label>}
          </article>); })}</div>}

        {pairs.length === 0 && !busy && !note && <ProfilePreview title="Kết quả đối chiếu sẽ có" text="Chọn ít nhất hai tài liệu rồi bấm Tìm cặp nghi vấn: hệ thống ghép những câu cùng chủ đề nhưng khác con số hoặc khác phủ định."
          items={[[GitCompareArrows, 'Cặp đặt đối diện', 'Hai câu của hai tài liệu cạnh nhau'], [Search, 'Tìm tại máy', 'Không dùng mô hình, xong ngay'], [Bot, 'Tác tử xét từng cặp', 'Mâu thuẫn, nhất quán hay không liên quan'],
            [Quote, 'Bấm để xem gốc', 'Mở đúng đoạn tài liệu chứa câu đó'], [UserCheck, 'Người duyệt', 'Sửa kết luận trước khi xuất'], [Download, 'Xuất báo cáo', 'CSV, Markdown, lưu để mở lại']]} />}

        {checked.length > 0 && !running && <div className="tv-actions is-end">
          <button className="btn btn-ghost" onClick={exportCsv}><Download size={15} />Xuất CSV</button>
          <button className="btn btn-ghost" onClick={exportMd}><Download size={15} />Xuất Markdown</button>
          <button className="btn btn-dark" onClick={save}><Save size={15} />Lưu báo cáo</button>
        </div>}
      </div>
      {viewer.modal}
    </main>
  );
};
