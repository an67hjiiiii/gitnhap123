import React, { useEffect, useRef, useState } from 'react';
import { ArrowUp, BookOpen, MessageCirclePlus, MessagesSquare } from 'lucide-react';
import { Conversation, ConversationMessage, getChunk, getConversation, getRawRun, listConversations, sendChat } from '../services/api';
import { answerText, Cap1Run } from '../services/adapt';
import { Markdown } from '../utils/markdown';
import { serverDate } from '../utils/time';
import { StudioModal } from './StudioModal';

const STATUS_LABEL: Record<string, string> = {
  COMPLETE: 'Đủ bằng chứng', PARTIAL: 'Một phần', NO_EVIDENCE: 'Không có bằng chứng', FAILED: 'Thất bại',
};

const citationsOf = (run?: Cap1Run | null): string[] =>
  [...new Set((run?.task_results || []).flatMap((r: any) => r.citations || []))] as string[];

// Trò chuyện nhiều lượt trong Studio: dùng cuộc trò chuyện của CAP1 (/api/conversations, /api/chat chế độ sản phẩm).
export const ChatStudio: React.FC = () => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [runs, setRuns] = useState<Record<string, Cap1Run>>({});
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chunk, setChunk] = useState<{ id: string; source?: string; text?: string; error?: string } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const refreshList = () => listConversations().then(setConversations).catch(err => setError(err.message));
  useEffect(() => { void refreshList(); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }); }, [messages, pending]);

  const open = async (id: string) => {
    setActiveId(id); setError(null);
    try {
      const conv = await getConversation(id);
      setMessages(conv.messages);
      const ids = conv.messages.filter(m => m.run_id && !runs[m.run_id]).map(m => m.run_id as string).slice(-20);
      const loaded = await Promise.all(ids.map(r => getRawRun(r).catch(() => null)));
      setRuns(prev => ({ ...prev, ...Object.fromEntries(loaded.filter(Boolean).map(r => [r!.run_id, r!])) }));
    } catch (err: any) { setError(err.message); }
  };

  const send = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    setPending(text); setDraft(''); setError(null);
    try {
      const run = await sendChat(text, activeId);
      setRuns(prev => ({ ...prev, [run.run_id]: run }));
      if (run.conversation_id) await open(run.conversation_id);
      await refreshList();
    } catch (err: any) { setError(err.message); setDraft(text); }
    finally { setPending(null); }
  };

  const showChunk = async (id: string) => {
    setChunk({ id });
    try { const c = await getChunk(id); setChunk({ id, source: c.source_name, text: c.text }); }
    catch (err: any) { setChunk({ id, error: err.message }); }
  };

  return (
    <main className="mn cht">
      <aside className="cht-list" aria-label="Các cuộc trò chuyện">
        <button className="btn btn-dark cht-new" onClick={() => { setActiveId(null); setMessages([]); setError(null); }}>
          <MessageCirclePlus size={15} />Cuộc trò chuyện mới
        </button>
        <ul>
          {conversations.length === 0 ? <li className="kb-none">Chưa có cuộc trò chuyện nào.</li> : conversations.map(c => (
            <li key={c.conversation_id}>
              <button className={`hist-row${activeId === c.conversation_id ? ' is-on' : ''}`} onClick={() => open(c.conversation_id)} aria-current={activeId === c.conversation_id ? 'true' : undefined}>
                <span className="hist-q">{c.title || 'Không tên'}</span>
                <time className="hist-t">{serverDate(c.updated_at).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' })}</time>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="cht-thread" aria-label="Nội dung trò chuyện">
        <div className="cht-msgs" aria-live="polite">
          {messages.length === 0 && !pending && <div className="cht-empty">
            <MessagesSquare size={22} />
            <h1>Hỏi đáp nhiều lượt trên kho tài liệu của bạn</h1>
            <p>Mỗi câu trả lời dựa trên tài liệu đã nạp và ghi nguồn. Câu hỏi sau hiểu được ngữ cảnh câu trước trong cùng cuộc trò chuyện.</p>
          </div>}
          {messages.map(m => {
            const run = m.run_id ? runs[m.run_id] : undefined;
            const cites = citationsOf(run);
            return m.role === 'USER'
              ? <div key={m.message_id} className="cht-msg is-user"><p>{m.content}</p></div>
              : <div key={m.message_id} className="cht-msg is-bot">
                  {run?.status && <span className={`cht-status is-${String(run.status).toLowerCase()}`}>{STATUS_LABEL[run.status] ?? run.status}</span>}
                  <div className="md"><Markdown text={answerText(m.content)} /></div>
                  {cites.length > 0 && <div className="cht-cites"><BookOpen size={13} />{cites.map(c => (
                    <button key={c} onClick={() => showChunk(c)} title="Xem đoạn tài liệu được trích">{c.split('_').slice(-2).join('_')}</button>
                  ))}</div>}
                </div>;
          })}
          {pending && <>
            <div className="cht-msg is-user"><p>{pending}</p></div>
            <div className="cht-msg is-bot is-wait"><span className="spin is-dark" />Đang tìm trong tài liệu và soạn câu trả lời…</div>
          </>}
          <div ref={endRef} />
        </div>
        {error && <p className="note is-error" role="alert">{error}</p>}
        <form className="composer cht-composer" onSubmit={send}>
          <textarea rows={2} value={draft} aria-label="Câu hỏi" placeholder="Hỏi về tài liệu trong kho của bạn…"
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(); } }} />
          <div className="composer-bar">
            <span className="composer-hint">Enter để gửi · Shift + Enter xuống dòng</span>
            <button type="submit" className="send" disabled={!!pending || !draft.trim()} aria-label="Gửi câu hỏi">{pending ? <span className="spin" /> : <ArrowUp size={18} />}</button>
          </div>
        </form>
      </section>

      {chunk && <StudioModal labelId="cht-chunk" size="md" icon={<BookOpen size={18} />} title="Đoạn tài liệu được trích" subtitle={chunk.source || chunk.id} onClose={() => setChunk(null)}
        footer={<button className="btn btn-dark" onClick={() => setChunk(null)}>Đóng</button>}>
        {chunk.error ? <p className="note is-error">{chunk.error}</p> : chunk.text == null ? <p className="muted-line"><span className="spin is-dark" />Đang tải…</p> : <pre className="chunk-pre">{chunk.text}</pre>}
      </StudioModal>}
    </main>
  );
};
