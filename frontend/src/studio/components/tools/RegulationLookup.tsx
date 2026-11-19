// Giáo dục · Tra cứu quy chế theo Điều: mục lục Điều/Chương cắt từ văn bản (không dùng mô hình) và hỏi đáp trả về
// đúng Điều; Điều được dẫn phải nằm trong các Điều hệ thống đã tìm.
import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, BookOpenText, Search, Send } from 'lucide-react';
import { Article, listArticles, lookupArticles } from '../../services/api';
import { Doc, DocPicker, ToolHeader } from '../analysis/shared';
import { Meta, useDocs } from '../CaseworkViews';

const FLAG: Record<string, string> = {
  no_article_cited: 'Câu trả lời không dẫn được Điều nào trong các Điều đã tìm; hãy đọc trực tiếp các Điều bên dưới.',
  numbers_not_in_articles: 'Câu trả lời có con số không có trong Điều được dẫn; hãy đối chiếu với nguyên văn.',
  no_article: 'Không tìm thấy Điều nào liên quan.',
};
const key = (a: Article) => `${a.source_name}#${a.number}`;

export const RegulationLookup: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const { pickable, picked, setPicked, ids } = useDocs(docs);
  const [articles, setArticles] = useState<Article[]>([]);
  const [open, setOpen] = useState<string>('');
  const [filter, setFilter] = useState('');
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<Awaited<ReturnType<typeof lookupArticles>> | null>(null);

  useEffect(() => {
    if (!ids.length) { setArticles([]); return; }
    let live = true;
    setBusy('index'); setError(null);
    listArticles(ids).then(r => { if (live) { setArticles(r.articles); setOpen(r.articles[0] ? key(r.articles[0]) : ''); } })
      .catch(e => live && setError(e.message)).finally(() => live && setBusy(''));
    return () => { live = false; };
  }, [ids.join('|')]);

  const shown = useMemo(() => articles.filter(a => !filter.trim() || `Điều ${a.number} ${a.title} ${a.text}`.toLowerCase().includes(filter.toLowerCase())), [articles, filter]);
  const current = articles.find(a => key(a) === open);
  const ask = async () => {
    setBusy('ask'); setError(null); setAnswer(null);
    try { const r = await lookupArticles(question.trim(), ids); setAnswer(r); const first = r.articles.find(a => r.cited.includes(key(a))) ?? r.articles[0]; if (first) setOpen(key(first)); }
    catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  return (
    <main className="pg tl tone-trace">
      <div className="pg-col tv-col">
        <ToolHeader Icon={BookOpenText} title="Tra cứu quy chế theo Điều" desc="Mục lục theo Chương, Điều của quy chế; hỏi một câu và nhận câu trả lời kèm đúng Điều để đọc nguyên văn." />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        <section className="tv-setup">
          <DocPicker docs={pickable} selected={picked} onChange={setPicked} legend="Quy chế, quy định" />
          <div className="tk-ask">
            <input className="dz-input" value={question} onChange={e => setQuestion(e.target.value)} maxLength={1000} placeholder="Ví dụ: Sinh viên bị buộc thôi học khi nào?"
              onKeyDown={e => { if (e.key === 'Enter' && question.trim().length >= 3 && articles.length && !busy) void ask(); }} aria-label="Câu hỏi về quy chế" />
            <button className="btn btn-dark" onClick={ask} disabled={!!busy || question.trim().length < 3 || !articles.length}>{busy === 'ask' ? <span className="spin" /> : <Send size={15} />}Hỏi</button>
          </div>
        </section>

        {answer && <section className="dz-card rl-answer">
          <p>{answer.answer || 'Chưa có câu trả lời.'}</p>
          {answer.cited.length > 0 && <p className="chips">Căn cứ: {answer.articles.filter(a => answer.cited.includes(key(a))).map(a =>
            <button key={key(a)} className="chip is-on" onClick={() => setOpen(key(a))}>Điều {a.number}. {a.title}{ids.length > 1 && ` (${a.source_name.replace(/\.[^.]+$/, '')})`}</button>)}</p>}
          {answer.flags.map(f => <p key={f} className="tv-flag"><AlertCircle size={13} />{FLAG[f] ?? f}</p>)}
          <Meta r={{ ...answer, removed: 0 }} what="mục" />
        </section>}

        {busy === 'index' && <p className="muted-line"><span className="spin is-dark" />Đang lập mục lục…</p>}
        {!busy && ids.length > 0 && articles.length === 0 && <p className="muted-line">Tài liệu đã chọn không chia theo Điều (không thấy dòng bắt đầu bằng "Điều 1", "Điều 2"…).</p>}
        {articles.length > 0 && <div className="rl-split">
          <nav className="rl-toc" aria-label="Mục lục Điều">
            <label className="search"><Search size={14} /><span className="sr">Lọc Điều</span><input type="search" value={filter} onChange={e => setFilter(e.target.value)} placeholder={`Lọc ${articles.length} Điều`} /></label>
            <ul>{shown.map((a, i) => <React.Fragment key={key(a)}>
              {a.chapter && a.chapter !== shown[i - 1]?.chapter && <li className="rl-chapter">{a.chapter}</li>}
              <li><button className={open === key(a) ? 'is-on' : ''} aria-current={open === key(a) ? 'true' : undefined} onClick={() => setOpen(key(a))}>
                <b>Điều {a.number}.</b> {a.title}{answer?.cited.includes(key(a)) && <i className="rl-dot" title="Được dẫn trong câu trả lời" />}</button></li>
            </React.Fragment>)}</ul>
          </nav>
          {current && <article className="dz-card rl-read"><small>{current.source_name}{current.chapter && ` · ${current.chapter}`}</small>
            <h3>Điều {current.number}. {current.title}</h3><pre className="chunk-pre">{current.text || '(Điều không có nội dung bên dưới tiêu đề)'}</pre></article>}
        </div>}
      </div>
    </main>
  );
};
