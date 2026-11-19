// Công cụ nghiệp vụ dùng chung cho các ngành: Kiểm tra điều kiện (một tình huống có đủ điều kiện theo quy định không)
// và Quy trình từng bước (các bước, người thực hiện, thời hạn, hồ sơ). Kết luận tổng do máy chủ suy ra bằng luật cố định.
import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, CircleHelp, Download, FileCheck2, ListOrdered, Scale, XCircle } from 'lucide-react';
import { checkConditions, ConditionOverall, ConditionResult, ConditionVerdict, extractProcedure, ProcedureResult } from '../services/api';
import { chunkLabel, Doc, DocPicker, docId, download, fmtSeconds, ToolHeader, useAnalysisData, useChunkViewer } from './analysis/shared';
import './profile/tools.css';
import './casework.css';

export interface CaseExample { question: string; case: string; topic: string }

const OVERALL: Record<ConditionOverall, { label: string; tone: string; Icon: typeof CheckCircle2; text: string }> = {
  ELIGIBLE: { label: 'Đủ điều kiện', tone: 'ok', Icon: CheckCircle2, text: 'Tình huống đáp ứng mọi điều kiện tìm thấy trong tài liệu.' },
  NOT_ELIGIBLE: { label: 'Chưa đủ điều kiện', tone: 'bad', Icon: XCircle, text: 'Có ít nhất một điều kiện tình huống không đáp ứng.' },
  INSUFFICIENT_INFO: { label: 'Thiếu thông tin để kết luận', tone: 'warn', Icon: CircleHelp, text: 'Tình huống chưa nêu đủ dữ kiện cho một số điều kiện; bổ sung rồi kiểm tra lại.' },
  NO_RULE: { label: 'Không tìm thấy quy định liên quan', tone: 'muted', Icon: CircleHelp, text: 'Tài liệu đã chọn không có đoạn nào nêu điều kiện cho câu hỏi này.' },
  UNRESOLVED: { label: 'Chưa trích được điều kiện', tone: 'warn', Icon: CircleHelp, text: 'Mô hình chưa nêu được điều kiện nào có căn cứ trong tài liệu (chỉ lặp lại tình huống). Hãy hỏi cụ thể hơn, ví dụ nêu tên quy định, rồi thử lại.' },
};
const FLAG_CORRECTED = 'Mô hình dẫn nhầm đoạn; đã chuyển sang đoạn chứa đúng con số của điều kiện.';
const VERDICT: Record<ConditionVerdict, { label: string; tone: string }> = {
  MET: { label: 'Đạt', tone: 'complete' }, NOT_MET: { label: 'Không đạt', tone: 'failed' }, UNKNOWN: { label: 'Chưa xác định', tone: 'partial' },
};
const FLAG: Record<string, string> = {
  numbers_not_in_source: 'Con số trong điều kiện không có trong đoạn trích nên không dùng để kết luận.',
  no_case_fact: 'Tình huống không nêu dữ kiện cho điều kiện này.',
  fact_not_in_case: 'Dữ kiện mô hình nêu có con số không có trong tình huống bạn nhập nên không dùng để kết luận.',
  invalid_model_output: 'Mô hình trả kết luận không hợp lệ.',
  deadline_not_in_source: 'Thời hạn mô hình nêu không có trong đoạn trích nên đã ẩn.',
  citation_corrected: FLAG_CORRECTED,
};

export function useDocs(docs: Doc[]) {
  const { allDocs } = useAnalysisData('condition_check');
  const pickable = allDocs.length ? allDocs : docs;
  const [picked, setPicked] = useState<Set<string>>(new Set());
  useEffect(() => { if (!picked.size && docs.length) setPicked(new Set(docs.map(docId))); }, [docs]);
  const ids = [...picked].filter(Boolean);
  const nameOf = (chunkId: string, evidence: { chunk_id: string; source_name: string }[]) => chunkLabel(chunkId, evidence.find(e => e.chunk_id === chunkId)?.source_name);
  return { pickable, picked, setPicked, ids, nameOf };
}

export const Meta: React.FC<{ r: { agent_name: string; input_tokens: number; output_tokens: number; latency_ms: number; removed: number }; what: string }> = ({ r, what }) => (
  <p className="is-muted cw-meta">{r.agent_name} · {(r.input_tokens + r.output_tokens).toLocaleString('vi-VN')} token · {fmtSeconds(r.latency_ms)} giây
    {r.removed > 0 && <> · đã bỏ {r.removed} {what} mô hình nêu nhưng không có căn cứ trong tài liệu</>}</p>
);

export const ConditionCheckView: React.FC<{ docs: Doc[]; example: CaseExample }> = ({ docs, example }) => {
  const { pickable, picked, setPicked, ids, nameOf } = useDocs(docs);
  const viewer = useChunkViewer();
  const [question, setQuestion] = useState('');
  const [caseText, setCaseText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ConditionResult | null>(null);
  const ready = question.trim().length >= 5 && caseText.trim().length >= 3 && ids.length > 0;

  const run = async () => {
    setBusy(true); setError(null); setResult(null);
    try { setResult(await checkConditions(question.trim(), caseText.trim(), ids)); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const exportMd = () => {
    if (!result) return;
    const o = OVERALL[result.overall];
    download('kiem-tra-dieu-kien.md', [`# Kiểm tra điều kiện`, '', `- Câu hỏi: ${question}`, `- Tình huống: ${caseText.replace(/\n/g, ' ')}`, `- Kết luận: **${o.label}**`, '',
      '| Điều kiện | Dữ kiện trong tình huống | Kết luận | Căn cứ |', '|---|---|---|---|',
      ...result.conditions.map(c => `| ${c.condition.replace(/\|/g, '/')} | ${(c.case_fact || '—').replace(/\|/g, '/')} | ${VERDICT[c.verdict].label} | ${nameOf(c.citation, result.evidence)} |`),
      '', '_Kết luận do luật cố định suy ra từ từng điều kiện có trích dẫn; là gợi ý, người có thẩm quyền quyết định._'].join('\n'), 'text/markdown;charset=utf-8');
  };
  const o = result ? OVERALL[result.overall] : null;

  return (
    <main className="pg tl tone-trace">
      <div className="pg-col tv-col">
        <ToolHeader Icon={Scale} title="Kiểm tra điều kiện" desc="Nhập một tình huống cụ thể; hệ thống tìm các điều kiện trong tài liệu, đối chiếu từng điều kiện kèm trích dẫn rồi kết luận." />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <label className="tv-field"><span>Câu hỏi</span>
            <input className="dz-input" value={question} onChange={e => setQuestion(e.target.value)} maxLength={1000} disabled={busy} placeholder={example.question} /></label>
          <label className="tv-field"><span>Tình huống, dữ kiện <small>(càng đủ con số càng kết luận chắc)</small></span>
            <textarea className="dz-input" rows={3} value={caseText} onChange={e => setCaseText(e.target.value)} maxLength={3000} disabled={busy} placeholder={example.case} /></label>
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} disabled={busy} legend="Tài liệu quy định" />
          <div className="tv-actions">
            <button className="btn btn-dark" onClick={run} disabled={!ready || busy}>{busy ? <span className="spin" /> : <Scale size={15} />}{busy ? 'Đang kiểm tra…' : 'Kiểm tra'}</button>
            <button type="button" className="btn btn-ghost" onClick={() => { setQuestion(example.question); setCaseText(example.case); }} disabled={busy}>Dùng ví dụ</button>
          </div>
        </section>

        {result && o && <>
          <section className={`cw-verdict is-${o.tone}`} role="status"><o.Icon size={22} /><div><b>{o.label}</b><p>{result.note || o.text}</p></div></section>
          {result.conditions.length > 0 && <div className="tbl"><table>
            <thead><tr><th>Điều kiện trong tài liệu</th><th>Dữ kiện trong tình huống</th><th>Kết luận</th><th>Căn cứ</th></tr></thead>
            <tbody>{result.conditions.map((c, i) => <tr key={i}>
              <td>{c.condition}{c.reason && <small className="cw-reason">{c.reason}</small>}{c.flags.map(f => <small key={f} className="tv-flag"><AlertCircle size={12} />{FLAG[f] ?? f}</small>)}</td>
              <td>{c.case_fact || <span className="is-muted">Không nêu</span>}</td>
              <td><span className={`cht-status is-${VERDICT[c.verdict].tone}`}>{VERDICT[c.verdict].label}</span></td>
              <td><button className="tv-cite-count" onClick={() => viewer.show(c.citation)}>{nameOf(c.citation, result.evidence)}</button></td>
            </tr>)}</tbody>
          </table></div>}
          <Meta r={result} what="điều kiện" />
          <p className="is-muted">Kết luận là gợi ý dựa trên tài liệu đã chọn; người có thẩm quyền quyết định.</p>
          <div className="tv-actions is-end"><button className="btn btn-ghost" onClick={exportMd}><Download size={15} />Xuất Markdown</button></div>
        </>}
      </div>
      {viewer.modal}
    </main>
  );
};

export const ProcedureView: React.FC<{ docs: Doc[]; example: CaseExample }> = ({ docs, example }) => {
  const { pickable, picked, setPicked, ids, nameOf } = useDocs(docs);
  const viewer = useChunkViewer();
  const [topic, setTopic] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProcedureResult | null>(null);
  const [done, setDone] = useState<Set<number>>(new Set());
  const ready = topic.trim().length >= 3 && ids.length > 0;

  const run = async () => {
    setBusy(true); setError(null); setResult(null); setDone(new Set());
    try { setResult(await extractProcedure(topic.trim(), ids)); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const exportMd = () => {
    if (!result) return;
    download('quy-trinh.md', [`# Quy trình: ${topic}`, '',
      ...result.steps.map(s => `${s.order}. ${s.action}${s.actor ? ` — ${s.actor}` : ''}${s.deadline ? ` (thời hạn: ${s.deadline})` : ''}${s.outputs ? `; giấy tờ/kết quả: ${s.outputs}` : ''} [${nameOf(s.citation, result.evidence)}]`),
      ...(result.documents.length ? ['', '## Hồ sơ cần chuẩn bị', ...result.documents.map(d => `- [ ] ${d.name} [${nameOf(d.citation, result.evidence)}]`)] : []),
      '', '_Mỗi bước có trích dẫn tài liệu gốc; bước không có căn cứ đã bị bỏ._'].join('\n'), 'text/markdown;charset=utf-8');
  };
  const progress = useMemo(() => (result?.steps.length ? Math.round((done.size / result.steps.length) * 100) : 0), [done, result]);

  return (
    <main className="pg tl tone-design">
      <div className="pg-col tv-col">
        <ToolHeader Icon={ListOrdered} title="Quy trình từng bước" desc="Nhập tên thủ tục hoặc quy trình; hệ thống lập các bước theo thứ tự, ai thực hiện, thời hạn, hồ sơ cần chuẩn bị, mỗi mục kèm trích dẫn." />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <label className="tv-field"><span>Thủ tục, quy trình</span>
            <input className="dz-input" value={topic} onChange={e => setTopic(e.target.value)} maxLength={400} disabled={busy} placeholder={example.topic}
              onKeyDown={e => { if (e.key === 'Enter' && ready && !busy) void run(); }} /></label>
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} disabled={busy} legend="Tài liệu quy định" />
          <div className="tv-actions">
            <button className="btn btn-dark" onClick={run} disabled={!ready || busy}>{busy ? <span className="spin" /> : <ListOrdered size={15} />}{busy ? 'Đang lập…' : 'Lập quy trình'}</button>
            <button type="button" className="btn btn-ghost" onClick={() => setTopic(example.topic)} disabled={busy}>Dùng ví dụ</button>
          </div>
        </section>

        {result && <>
          {result.steps.length === 0
            ? <section className="cw-verdict is-muted" role="status"><CircleHelp size={22} /><div><b>Chưa lập được quy trình</b><p>{result.note || 'Tài liệu đã chọn không mô tả các bước của thủ tục này.'}</p></div></section>
            : <section className="cw-steps" aria-label="Các bước">
                <div className="cw-progress"><i style={{ width: `${progress}%` }} /><span>Đã làm {done.size}/{result.steps.length} bước</span></div>
                <ol>{result.steps.map(s => {
                  const on = done.has(s.order);
                  return <li key={s.order} className={on ? 'is-done' : ''}>
                    <label className="cw-check"><input type="checkbox" checked={on} onChange={() => setDone(prev => { const n = new Set(prev); on ? n.delete(s.order) : n.add(s.order); return n; })} />
                      <span className="cw-num">{s.order}</span></label>
                    <div className="cw-body"><b>{s.action}</b>
                      <dl>{s.actor && <><dt>Thực hiện</dt><dd>{s.actor}</dd></>}{s.deadline && <><dt>Thời hạn</dt><dd>{s.deadline}</dd></>}{s.outputs && <><dt>Giấy tờ, kết quả</dt><dd>{s.outputs}</dd></>}</dl>
                      {s.flags.map(f => <small key={f} className="tv-flag"><AlertCircle size={12} />{FLAG[f] ?? f}</small>)}
                      <button className="tv-cite-count" onClick={() => viewer.show(s.citation)}>{nameOf(s.citation, result.evidence)}</button>
                    </div>
                  </li>;
                })}</ol>
              </section>}
          {result.documents.length > 0 && <section className="dz-card cw-docs"><header><h3><FileCheck2 size={16} />Hồ sơ cần chuẩn bị</h3></header>
            <ul>{result.documents.map((d, i) => <li key={i}><span>{d.name}</span><button className="tv-cite-count" onClick={() => viewer.show(d.citation)}>{nameOf(d.citation, result.evidence)}</button></li>)}</ul></section>}
          <Meta r={result} what="mục" />
          {result.steps.length > 0 && <div className="tv-actions is-end"><button className="btn btn-ghost" onClick={exportMd}><Download size={15} />Xuất danh sách việc (Markdown)</button></div>}
        </>}
      </div>
      {viewer.modal}
    </main>
  );
};
