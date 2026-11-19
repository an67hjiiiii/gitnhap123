// Giáo dục · Tạo câu hỏi ôn tập: trắc nghiệm 4 phương án từ tài liệu đã chọn; máy chủ bỏ câu có đáp án không nằm trong
// đoạn trích. Có chế độ làm thử (chấm ngay) và xuất đề kèm đáp án.
import React, { useState } from 'react';
import { AlertCircle, CheckCircle2, Download, Eye, EyeOff, GraduationCap, RotateCcw, XCircle } from 'lucide-react';
import { generateItems, QuizItem } from '../../services/api';
import { csvCell, Doc, DocPicker, download, ToolHeader, useChunkViewer } from '../analysis/shared';
import { Meta, useDocs } from '../CaseworkViews';

const LETTER = ['A', 'B', 'C', 'D'];

export const QuizBuilder: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const { pickable, picked, setPicked, ids, nameOf } = useDocs(docs);
  const viewer = useChunkViewer();
  const [count, setCount] = useState(8);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<(Awaited<ReturnType<typeof generateItems<QuizItem>>>) | null>(null);
  const [picks, setPicks] = useState<Record<number, number>>({});
  const [reveal, setReveal] = useState(false);

  const run = async () => {
    setBusy(true); setError(null); setResult(null); setPicks({}); setReveal(false);
    try {
      const r = await generateItems<QuizItem>('quiz', ids, count);
      setResult(r);
      if (!r.items.length) setError('Chưa tạo được câu hỏi có căn cứ từ tài liệu này. Thử chọn tài liệu khác hoặc ít câu hơn.');
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const items = result?.items ?? [];
  const answered = Object.keys(picks).length;
  const correct = items.filter((q, i) => picks[i] === q.answer).length;
  const exportMd = () => download('cau-hoi-on-tap.md', ['# Câu hỏi ôn tập', '',
    ...items.flatMap((q, i) => [`**Câu ${i + 1}.** ${q.question}`, ...q.options.map((o, k) => `- ${LETTER[k]}. ${o}`), '']),
    '## Đáp án', ...items.map((q, i) => `${i + 1}. ${LETTER[q.answer]}: ${q.explanation || q.options[q.answer]} (${nameOf(q.citation, result?.evidence ?? [])})`)].join('\n'), 'text/markdown;charset=utf-8');
  const exportCsv = () => download('cau-hoi-on-tap.csv', '﻿' + [['Câu hỏi', 'A', 'B', 'C', 'D', 'Đáp án', 'Giải thích'].map(csvCell).join(','),
    ...items.map(q => [q.question, ...q.options, LETTER[q.answer], q.explanation].map(csvCell).join(','))].join('\r\n'), 'text/csv;charset=utf-8');

  return (
    <main className="pg tl tone-evaluation">
      <div className="pg-col tv-col">
        <ToolHeader Icon={GraduationCap} title="Tạo câu hỏi ôn tập" desc="Tạo câu trắc nghiệm 4 phương án từ bài giảng, giáo trình hoặc quy chế; mỗi câu có đáp án, giải thích và trích dẫn đoạn gốc." />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} disabled={busy} legend="Tài liệu nguồn" />
          <div className="tv-actions">
            <label className="tk-inline">Số câu <select value={count} onChange={e => setCount(Number(e.target.value))} disabled={busy}>{[5, 8, 10, 15].map(n => <option key={n} value={n}>{n}</option>)}</select></label>
            <button className="btn btn-dark" onClick={run} disabled={busy || ids.length === 0}>{busy ? <span className="spin" /> : <GraduationCap size={15} />}{busy ? 'Đang tạo…' : 'Tạo câu hỏi'}</button>
          </div>
        </section>

        {items.length > 0 && <>
          <div className="row-head">
            <p className="muted-line">{items.length} câu · đã làm {answered}/{items.length}{answered > 0 && <> · đúng <b>{correct}</b></>}</p>
            <div className="tv-actions">
              <button className="btn btn-ghost" onClick={() => setReveal(v => !v)}>{reveal ? <EyeOff size={15} /> : <Eye size={15} />}{reveal ? 'Ẩn đáp án' : 'Hiện đáp án'}</button>
              <button className="btn btn-ghost" onClick={() => { setPicks({}); setReveal(false); }} disabled={!answered}><RotateCcw size={15} />Làm lại</button>
            </div>
          </div>
          <ol className="qz-list">{items.map((q, i) => {
            const mine = picks[i]; const show = reveal || mine !== undefined;
            return <li key={i} className="dz-card qz-card">
              <p className="qz-q"><b>Câu {i + 1}.</b> {q.question}</p>
              <div className="qz-opts" role="radiogroup" aria-label={`Phương án câu ${i + 1}`}>{q.options.map((o, k) => {
                const state = show ? (k === q.answer ? 'is-right' : k === mine ? 'is-wrong' : '') : '';
                return <button key={k} role="radio" aria-checked={mine === k} className={`qz-opt ${state}`} disabled={mine !== undefined}
                  onClick={() => setPicks(p => ({ ...p, [i]: k }))}><b>{LETTER[k]}</b><span>{o}</span>
                  {state === 'is-right' && <CheckCircle2 size={15} />}{state === 'is-wrong' && <XCircle size={15} />}</button>;
              })}</div>
              {show && <p className="qz-exp">{q.explanation} <button className="tv-cite-count" onClick={() => viewer.show(q.citation)}>{nameOf(q.citation, result?.evidence ?? [])}</button></p>}
            </li>;
          })}</ol>
          {result && <Meta r={{ ...result, removed: result.removed ?? 0 }} what="câu" />}
          <div className="tv-actions is-end">
            <button className="btn btn-ghost" onClick={exportCsv}><Download size={15} />Xuất CSV</button>
            <button className="btn btn-dark" onClick={exportMd}><Download size={15} />Xuất đề và đáp án</button>
          </div>
        </>}
      </div>
      {viewer.modal}
    </main>
  );
};
