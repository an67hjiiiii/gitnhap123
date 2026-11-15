// Trình đọc tài liệu: xem toàn văn, bôi đen một đoạn để mô hình cục bộ giải thích bằng lời dễ hiểu,
// và chuyển sang tài liệu cùng chủ đề (độ trùng từ ngữ, tính tại máy).
import React, { useEffect, useRef, useState } from 'react';
import { ArrowLeft, BookOpen, Check, Copy, Lightbulb, Link2, X } from 'lucide-react';
import { explainSelection, getDocumentChunks, RelatedDoc, relatedDocs } from '../services/api';
import { ChunkInfo } from '../types';
import { Markdown } from '../utils/markdown';
import { StudioModal } from './StudioModal';
import { fmtSeconds } from './analysis/shared';

interface Explained { quote: string; text?: string; example?: string; error?: string; tokens?: number; ms?: number }
const CONTEXT_CHARS = 3800;

export function DocumentReader({ sourceId, sourceName, onClose }: { sourceId: string; sourceName?: string; onClose: () => void }) {
  const [trail, setTrail] = useState<{ id: string; name?: string }[]>([{ id: sourceId, name: sourceName }]);
  const cur = trail[trail.length - 1];
  const [chunks, setChunks] = useState<ChunkInfo[] | null>(null);
  const [name, setName] = useState(sourceName || '');
  const [related, setRelated] = useState<RelatedDoc[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<{ text: string; context: string; x: number; y: number } | null>(null);
  const [notes, setNotes] = useState<Explained[]>([]);
  const [copied, setCopied] = useState(false);
  const artRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    setChunks(null); setRelated(null); setError(null); setSel(null);
    getDocumentChunks(cur.id).then(c => { if (alive) { setChunks(c); artRef.current?.scrollTo({ top: 0 }); } }).catch(e => alive && setError(e.message));
    relatedDocs(cur.id).then(r => alive && setRelated(r.related)).catch(() => alive && setRelated([]));
    return () => { alive = false; };
  }, [cur.id]);
  useEffect(() => { if (cur.name) setName(cur.name); }, [cur.name]);

  // Theo dõi vùng bôi đen trong bài (chuột hoặc nhấn giữ trên điện thoại).
  useEffect(() => {
    let timer = 0;
    const onChange = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const s = window.getSelection(), art = artRef.current;
        if (!s || s.isCollapsed || !s.rangeCount || !art || !chunks) { setSel(null); return; }
        const range = s.getRangeAt(0);
        if (!art.contains(range.commonAncestorContainer)) { setSel(null); return; }
        const text = s.toString().replace(/\s+/g, ' ').trim();
        if (text.length < 2 || text.length > 1500) { setSel(null); return; }
        const start = range.startContainer.nodeType === 1 ? range.startContainer as Element : range.startContainer.parentElement;
        const idx = Number(start?.closest('[data-chunk]')?.getAttribute('data-chunk') ?? 0);
        const context = [chunks[idx]?.content, chunks[idx - 1]?.content, chunks[idx + 1]?.content].filter(Boolean).join('\n\n').slice(0, CONTEXT_CHARS);
        const r = range.getBoundingClientRect(), box = art.getBoundingClientRect();
        setSel({ text, context, x: Math.min(Math.max(r.left - box.left + r.width / 2, 70), box.width - 70), y: r.top - box.top + art.scrollTop });
      }, 180);
    };
    document.addEventListener('selectionchange', onChange);
    return () => { document.removeEventListener('selectionchange', onChange); window.clearTimeout(timer); };
  }, [chunks]);

  const explain = async () => {
    if (!sel) return;
    const { text, context } = sel;
    setSel(null); window.getSelection()?.removeAllRanges();
    setNotes(n => [{ quote: text }, ...n].slice(0, 6));
    const done = (patch: Partial<Explained>) => setNotes(n => n.map(x => x.quote === text && x.text === undefined && x.error === undefined ? { ...x, ...patch } : x));
    try {
      const r = await explainSelection(name, text, context);
      done({ text: r.explanation, example: r.example, tokens: r.input_tokens + r.output_tokens, ms: r.latency_ms });
    } catch (e: any) { done({ error: e.message }); }
  };
  const copy = () => { if (sel) { void navigator.clipboard.writeText(sel.text); setCopied(true); window.setTimeout(() => setCopied(false), 1500); } };
  const open = (d: RelatedDoc) => { setTrail(t => [...t, { id: d.source_id, name: d.source_name }]); };

  return (
    <StudioModal labelId="reader-title" icon={<BookOpen size={18} />} title={name || 'Tài liệu'}
      subtitle={chunks ? `${chunks.length} đoạn · ${chunks.reduce((a, c) => a + c.content.split(/\s+/).length, 0).toLocaleString('vi-VN')} từ · bôi đen một đoạn để được giải thích` : 'Đang tải…'}
      onClose={onClose}
      toolbar={trail.length > 1 ? <button className="btn btn-ghost is-sm" onClick={() => setTrail(t => t.slice(0, -1))}><ArrowLeft size={14} />Quay lại {trail[trail.length - 2].name || 'tài liệu trước'}</button> : undefined}
      footer={<><span className="mo-note">Giải thích do mô hình cục bộ viết dựa trên đoạn xung quanh; nên đối chiếu lại với tài liệu.</span><button className="btn btn-dark" onClick={onClose}>Đóng</button></>}>
      <div className="rd">
        <div className="rd-art" ref={artRef}>
          {error ? <p className="note is-error">{error}</p> : !chunks ? <p className="muted-line"><span className="spin is-dark" />Đang tải tài liệu…</p>
            : chunks.length === 0 ? <p className="is-muted">Tài liệu không có nội dung chữ.</p>
            : chunks.map((c, i) => <section key={c.id} data-chunk={i} className="md"><Markdown text={c.content} /></section>)}
          {sel && <div className="rd-pop" style={{ left: sel.x, top: Math.max(sel.y - 46, 4) }} onMouseDown={e => e.preventDefault()}>
            <button type="button" onClick={explain}><Lightbulb size={14} />Giải thích</button>
            <button type="button" onClick={copy} aria-label="Sao chép đoạn đã chọn">{copied ? <Check size={14} /> : <Copy size={14} />}</button>
          </div>}
        </div>
        <aside className="rd-side">
          <section>
            <h3><Lightbulb size={15} />Giải thích</h3>
            {notes.length === 0 ? <p className="is-muted">Bôi đen một từ hoặc một đoạn khó hiểu trong tài liệu, rồi bấm <b>Giải thích</b>.</p> :
              <ul className="rd-notes">{notes.map((n, i) => <li key={`${n.quote}-${i}`}>
                <blockquote>{n.quote.length > 160 ? `${n.quote.slice(0, 160)}…` : n.quote}</blockquote>
                {n.error ? <p className="note is-error">{n.error}</p> : n.text === undefined ? <p className="muted-line"><span className="spin is-dark" />Đang giải thích…</p> : <>
                  <p>{n.text}</p>
                  {n.example && <p className="rd-ex"><b>Ví dụ:</b> {n.example}</p>}
                  <small>{n.tokens?.toLocaleString('vi-VN')} token · {fmtSeconds(n.ms || 0)} giây</small>
                </>}
                <button type="button" className="rd-x" aria-label="Xóa giải thích này" onClick={() => setNotes(list => list.filter((_, j) => j !== i))}><X size={13} /></button>
              </li>)}</ul>}
          </section>
          <section>
            <h3><Link2 size={15} />Tài liệu liên quan</h3>
            {related === null ? <p className="muted-line"><span className="spin is-dark" />Đang tìm…</p> : related.filter(r => r.score > 0).length === 0 ? <p className="is-muted">Chưa thấy tài liệu cùng chủ đề.</p> :
              <ul className="rd-rel">{related.filter(r => r.score > 0).map(r => <li key={r.source_id}>
                <button type="button" onClick={() => open(r)}>
                  <b>{r.source_name.replace(/\.[^.]+$/, '').replace(/_/g, ' ')}</b>
                  <span className="dp-meter"><i style={{ width: `${Math.round(r.score * 100)}%` }} /></span>
                  <small>{Math.round(r.score * 100)}% · {r.shared_terms.slice(0, 3).join(', ')}</small>
                </button>
              </li>)}</ul>}
          </section>
        </aside>
      </div>
    </StudioModal>
  );
}
