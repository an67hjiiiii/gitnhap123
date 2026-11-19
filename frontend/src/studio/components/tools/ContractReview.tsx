// Pháp lý · Rà soát hợp đồng: kiểm các nội dung chủ yếu theo Điều 398 BLDS 2015 (+ thực hành soạn thảo) và tìm điều khoản
// rủi ro; điều khoản rủi ro phải trích được nguyên văn trong hợp đồng, nếu không thì bị bỏ.
import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, AlertTriangle, ChevronDown, Download, FileText, Square } from 'lucide-react';
import { checkRequirement, ContractRisk, contractCriteria, contractRisks, TraceRequirement, TraceResult } from '../../services/api';
import { chunkLabel, Doc, docId, download, ToolHeader, useChunkViewer } from '../analysis/shared';

const ST = { COVERED: ['Có', 'complete'], PARTIAL: ['Chưa rõ', 'partial'], MISSING: ['Chưa thấy', 'failed'], ERROR: ['Lỗi', 'failed'] } as const;
const LEVEL = { HIGH: 'Cao', MEDIUM: 'Trung bình', LOW: 'Thấp' } as const;

export const ContractReview: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const viewer = useChunkViewer();
  const [contract, setContract] = useState('');
  const [criteria, setCriteria] = useState<TraceRequirement[]>([]);
  const [results, setResults] = useState<Record<string, TraceResult>>({});
  const [risks, setRisks] = useState<Awaited<ReturnType<typeof contractRisks>> | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stop = useRef(false);

  useEffect(() => { contractCriteria().then(r => setCriteria(r.criteria)).catch(e => setError(e.message)); }, []);
  useEffect(() => { if (!contract && docs.length) setContract(docId(docs.find(d => /hop.?dong|hợp đồng|contract/i.test(d.source_file)) ?? docs[0])); }, [docs]);
  const name = docs.find(d => docId(d) === contract)?.source_file ?? '';

  const run = async () => {
    stop.current = false; setRunning(true); setError(null); setResults({}); setRisks(null);
    const riskJob = contractRisks([contract]).then(setRisks).catch(e => setError(e.message));
    for (const c of criteria) {
      if (stop.current) break;
      try { const r = await checkRequirement(c, [contract]); setResults(p => ({ ...p, [c.req_id]: r })); }
      catch (e: any) { setResults(p => ({ ...p, [c.req_id]: { req_id: c.req_id, status: 'ERROR', agent: '', agent_name: '', citations: [], evidence: [], covered_points: [], missing_points: [], note: e.message, flags: [], input_tokens: 0, output_tokens: 0, latency_ms: 0 } })); }
    }
    await riskJob; setRunning(false);
  };
  const groups = [...new Set(criteria.map(c => c.group ?? ''))];
  const exportMd = () => download(`ra-soat-hop-dong-${name.replace(/\.[^.]+$/, '')}.md`, [`# Rà soát hợp đồng: ${name}`, '',
    ...groups.flatMap(g => [`## ${g}`, ...criteria.filter(c => c.group === g).map(c => { const r = results[c.req_id]; return `- [${r ? ST[r.status][0] : 'Chưa kiểm'}] ${c.title}${r?.missing_points.length ? ` — còn thiếu: ${r.missing_points.join('; ')}` : ''}`; }), '']),
    '## Điều khoản cần lưu ý', ...(risks?.risks.length ? risks.risks.map(r => `- (${LEVEL[r.level]}) "${r.quote}" — ${r.reason}`) : ['- Không thấy điều khoản rủi ro có trích dẫn.']),
    '', '_Điều 398 BLDS 2015 liệt kê nội dung các bên có thể thỏa thuận; thiếu một nội dung không đồng nghĩa hợp đồng vô hiệu. Kết quả là gợi ý, không thay ý kiến luật sư._'].join('\n'), 'text/markdown;charset=utf-8');
  const done = Object.keys(results).length;

  return (
    <main className="pg tl tone-security">
      <div className="pg-col tv-col">
        <ToolHeader Icon={FileText} title="Rà soát hợp đồng" desc="Kiểm hợp đồng có đủ các nội dung chủ yếu theo Điều 398 Bộ luật Dân sự 2015 và chỉ ra điều khoản bất lợi, mơ hồ, kèm nguyên văn." />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <label className="tv-field"><span>Hợp đồng cần rà soát</span>
            <span className="wb-select"><select value={contract} onChange={e => { setContract(e.target.value); setResults({}); setRisks(null); }} disabled={running}>
              <option value="">Chọn tài liệu…</option>{docs.map(d => <option key={docId(d)} value={docId(d)}>{d.source_file}</option>)}</select><ChevronDown size={16} aria-hidden="true" /></span></label>
          <div className="tv-actions">
            {running ? <button className="btn btn-danger" onClick={() => { stop.current = true; }}><Square size={14} />Dừng</button>
              : <button className="btn btn-dark" onClick={run} disabled={!contract || !criteria.length}><FileText size={15} />Rà soát {criteria.length} nội dung</button>}
            {running && <span className="muted-line"><span className="spin is-dark" />Đã kiểm {done}/{criteria.length}</span>}
          </div>
        </section>
        {risks && !risks.looks_like_contract && <div className="note is-error" role="alert"><AlertCircle size={16} />
          <span>Tài liệu "{name}" không có chữ "hợp đồng" hay "Bên A/Bên B", có thể không phải hợp đồng. Kết quả bên dưới không có ý nghĩa nếu chọn nhầm tài liệu.</span></div>}
        {(done > 0 || risks) && <div className="cr-split">
          <section className="dz-card">{groups.map(g => <div key={g} className="cr-group"><h3>{g}</h3><ul>{criteria.filter(c => c.group === g).map(c => {
            const r = results[c.req_id];
            return <li key={c.req_id}><span className={`cht-status is-${r ? ST[r.status][1] : 'muted'}`}>{r ? ST[r.status][0] : running ? 'Đang chờ' : '—'}</span>
              <div><b>{c.title}</b>{r?.note && <small className="cw-reason">{r.note}</small>}
                {r?.citations.map(cid => <button key={cid} className="tv-cite-count" onClick={() => viewer.show(cid)}>{chunkLabel(cid, r.evidence.find(e => e.chunk_id === cid)?.source_name)}</button>)}</div></li>;
          })}</ul></div>)}
            <p className="is-muted">Điều 398 liệt kê nội dung các bên có thể thỏa thuận; thiếu một nội dung không có nghĩa hợp đồng vô hiệu.</p></section>
          <section className="dz-card"><h3><AlertTriangle size={16} />Điều khoản cần lưu ý</h3>
            {!risks ? <p className="muted-line"><span className="spin is-dark" />Đang đọc hợp đồng…</p>
              : risks.risks.length === 0 ? <p className="is-muted">Không thấy điều khoản rủi ro có trích dẫn nguyên văn.</p>
              : <ul className="cr-risks">{risks.risks.map((r, i) => <li key={i} className={`is-${r.level.toLowerCase()}`}>
                <span className="cr-level">{LEVEL[r.level]}</span><blockquote>“{r.quote}”</blockquote><p>{r.reason}</p>
                <button className="tv-cite-count" onClick={() => viewer.show(r.citation)}>{chunkLabel(r.citation, risks.evidence?.find(e => e.chunk_id === r.citation)?.source_name)}</button></li>)}</ul>}
            {risks && (risks.removed ?? 0) > 0 && <p className="is-muted">Đã bỏ {risks.removed} điều khoản mô hình nêu nhưng không có nguyên văn trong hợp đồng.</p>}
          </section>
        </div>}
        {!running && done > 0 && <div className="tv-actions is-end"><button className="btn btn-ghost" onClick={exportMd}><Download size={15} />Xuất biên bản rà soát</button></div>}
      </div>
      {viewer.modal}
    </main>
  );
};
