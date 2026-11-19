// Pháp lý · Hồ sơ thủ tục: giấy tờ cần nộp (người dùng đánh dấu đã có -> biết còn thiếu gì), các bước, thời hạn, lệ phí.
// Mỗi mục có trích dẫn; mục không có căn cứ đã bị máy chủ bỏ.
import React, { useState } from 'react';
import { AlertCircle, CheckCircle2, ClipboardList, Download, FolderCheck } from 'lucide-react';
import { extractProcedure, ProcedureResult } from '../../services/api';
import { Doc, DocPicker, download, ToolHeader, useChunkViewer } from '../analysis/shared';
import { Meta, useDocs } from '../CaseworkViews';

export const DossierChecklist: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const { pickable, picked, setPicked, ids, nameOf } = useDocs(docs);
  const viewer = useChunkViewer();
  const [topic, setTopic] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProcedureResult | null>(null);
  const [have, setHave] = useState<Set<number>>(new Set());

  const run = async () => {
    setBusy(true); setError(null); setResult(null); setHave(new Set());
    try { setResult(await extractProcedure(topic.trim(), ids)); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const docsList = result?.documents ?? [];
  const missing = docsList.filter((_, i) => !have.has(i));
  const exportMd = () => result && download('ho-so-thu-tuc.md', [`# Hồ sơ: ${topic}`, '', '## Giấy tờ cần nộp', ...docsList.map((d, i) => `- [${have.has(i) ? 'x' : ' '}] ${d.name}`),
    '', '## Các bước', ...result.steps.map(s => `${s.order}. ${s.action}${s.actor ? ` — ${s.actor}` : ''}${s.deadline ? ` (thời hạn: ${s.deadline})` : ''}`),
    ...(result.fees.length ? ['', '## Lệ phí', ...result.fees.map(f => `- ${f.text}`)] : [])].join('\n'), 'text/markdown;charset=utf-8');

  return (
    <main className="pg tl tone-design">
      <div className="pg-col tv-col">
        <ToolHeader Icon={FolderCheck} title="Hồ sơ thủ tục" desc="Nhập tên thủ tục; nhận danh mục giấy tờ cần nộp để đánh dấu, biết ngay còn thiếu gì, kèm các bước, thời hạn và lệ phí theo văn bản." />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <label className="tv-field"><span>Thủ tục</span>
            <input className="dz-input" value={topic} onChange={e => setTopic(e.target.value)} maxLength={400} disabled={busy} placeholder="Ví dụ: Đăng ký thành lập doanh nghiệp"
              onKeyDown={e => { if (e.key === 'Enter' && topic.trim().length >= 3 && ids.length && !busy) void run(); }} /></label>
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} disabled={busy} legend="Văn bản quy định thủ tục" />
          <div className="tv-actions"><button className="btn btn-dark" onClick={run} disabled={busy || topic.trim().length < 3 || !ids.length}>{busy ? <span className="spin" /> : <ClipboardList size={15} />}{busy ? 'Đang lập…' : 'Lập danh mục hồ sơ'}</button></div>
        </section>
        {result && <>
          {docsList.length > 0
            ? <section className={`cw-verdict is-${missing.length ? 'warn' : 'ok'}`} role="status">{missing.length ? <AlertCircle size={22} /> : <CheckCircle2 size={22} />}
                <div><b>{missing.length ? `Còn thiếu ${missing.length}/${docsList.length} giấy tờ` : 'Đã đủ giấy tờ theo danh mục'}</b><p>Đánh dấu giấy tờ bạn đã có ở danh mục bên dưới.</p></div></section>
            : <section className="cw-verdict is-muted" role="status"><AlertCircle size={22} /><div><b>Văn bản không nêu danh mục giấy tờ</b><p>{result.note || 'Thử chọn văn bản khác hoặc ghi tên thủ tục cụ thể hơn.'}</p></div></section>}
          <div className="cr-split">
            {docsList.length > 0 && <section className="dz-card"><h3>Giấy tờ cần nộp</h3><ul className="dc-list">{docsList.map((d, i) => <li key={i}>
              <label><input type="checkbox" checked={have.has(i)} onChange={() => setHave(h => { const n = new Set(h); n.has(i) ? n.delete(i) : n.add(i); return n; })} /><span>{d.name}</span></label>
              <button className="tv-cite-count" onClick={() => viewer.show(d.citation)}>{nameOf(d.citation, result.evidence)}</button></li>)}</ul></section>}
            <section className="dz-card"><h3>Các bước</h3>{result.steps.length === 0 ? <p className="is-muted">Văn bản không mô tả các bước.</p> : <ol className="dc-steps">{result.steps.map(s => <li key={s.order}>
              <b>{s.action}</b>{(s.actor || s.deadline) && <small>{[s.actor, s.deadline && `thời hạn: ${s.deadline}`].filter(Boolean).join(' · ')}</small>}
              <button className="tv-cite-count" onClick={() => viewer.show(s.citation)}>{nameOf(s.citation, result.evidence)}</button></li>)}</ol>}
              {result.fees.length > 0 && <><h3>Lệ phí</h3><ul className="dc-list">{result.fees.map((f, i) => <li key={i}><span>{f.text}</span><button className="tv-cite-count" onClick={() => viewer.show(f.citation)}>{nameOf(f.citation, result.evidence)}</button></li>)}</ul></>}
            </section>
          </div>
          <Meta r={result} what="mục" />
          <div className="tv-actions is-end"><button className="btn btn-ghost" onClick={exportMd}><Download size={15} />Xuất danh mục</button></div>
        </>}
      </div>
      {viewer.modal}
    </main>
  );
};
