// Nhân sự · Hỏi đáp chính sách: bộ câu hỏi thường gặp sinh từ nội quy; câu trả lời có con số không nằm trong đoạn trích bị bỏ.
import React, { useMemo, useState } from 'react';
import { AlertCircle, Download, MessageCircleQuestion, Search } from 'lucide-react';
import { FaqItem, generateItems } from '../../services/api';
import { Doc, DocPicker, download, ToolHeader, useChunkViewer } from '../analysis/shared';
import { Meta, useDocs } from '../CaseworkViews';

export const PolicyFaq: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const { pickable, picked, setPicked, ids, nameOf } = useDocs(docs);
  const viewer = useChunkViewer();
  const [count, setCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Awaited<ReturnType<typeof generateItems<FaqItem>>> | null>(null);
  const [query, setQuery] = useState('');

  const run = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const r = await generateItems<FaqItem>('faq', ids, count);
      setResult(r);
      if (!r.items.length) setError('Chưa tạo được câu hỏi có căn cứ từ tài liệu này.');
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const items = useMemo(() => (result?.items ?? []).filter(i => !query.trim() || `${i.question} ${i.answer}`.toLowerCase().includes(query.toLowerCase())), [result, query]);
  const exportMd = () => result && download('hoi-dap-chinh-sach.md', ['# Hỏi đáp chính sách', '',
    ...result.items.flatMap(i => [`### ${i.question}`, i.answer, `_Căn cứ: ${nameOf(i.citation, result.evidence ?? [])}_`, ''])].join('\n'), 'text/markdown;charset=utf-8');

  return (
    <main className="pg tl tone-consistency">
      <div className="pg-col tv-col">
        <ToolHeader Icon={MessageCircleQuestion} title="Hỏi đáp chính sách cho nhân viên" desc="Tạo bộ câu hỏi thường gặp từ nội quy, chính sách; mỗi câu trả lời có trích dẫn, xuất để gửi nhân viên hoặc đăng nội bộ." />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} disabled={busy} legend="Nội quy, chính sách" />
          <div className="tv-actions">
            <label className="tk-inline">Số câu <select value={count} onChange={e => setCount(Number(e.target.value))} disabled={busy}>{[5, 10, 15].map(n => <option key={n} value={n}>{n}</option>)}</select></label>
            <button className="btn btn-dark" onClick={run} disabled={busy || !ids.length}>{busy ? <span className="spin" /> : <MessageCircleQuestion size={15} />}{busy ? 'Đang tạo…' : 'Tạo bộ hỏi đáp'}</button>
          </div>
        </section>
        {result && result.items.length > 0 && <>
          <div className="row-head"><label className="search"><Search size={14} /><span className="sr">Tìm câu hỏi</span><input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Tìm trong hỏi đáp" /></label></div>
          <div className="faq-list">{items.map((i, k) => <details key={k} className="dz-card faq-item" open={k === 0}>
            <summary>{i.question}</summary><p>{i.answer}</p>
            <button className="tv-cite-count" onClick={() => viewer.show(i.citation)}>{nameOf(i.citation, result.evidence ?? [])}</button>
          </details>)}</div>
          <Meta r={{ ...result, removed: result.removed ?? 0 }} what="câu" />
          <div className="tv-actions is-end"><button className="btn btn-dark" onClick={exportMd}><Download size={15} />Xuất hỏi đáp</button></div>
        </>}
      </div>
      {viewer.modal}
    </main>
  );
};
