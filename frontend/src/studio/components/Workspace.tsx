import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, BookOpen, ChevronDown, Footprints, Sparkles, Users, Volume2, VolumeX, Zap, Microscope } from 'lucide-react';
import { ConversationMessage, getChunk, getConversation, getRawRun, sendAnalysis, sendChat, explainFailure } from '../services/api';
import { adaptRun, answerText, Cap1Run, CONDITION_LABEL } from '../services/adapt';
import { Markdown } from '../utils/markdown';
import { AssistantRobot } from './robot/AssistantRobot';
import { useRobotAssistant } from './robot/RobotContext';
import { RobotState } from './robot/robotEngine';
import { PIPELINE_STEPS, PipelineStep } from './ExecutionFlowGraph';
import { NodeTraceModal } from './NodeTraceModal';
import { StudioModal } from './StudioModal';
import { ModeExecutionResult } from '../types';

// Không gian làm việc duy nhất: hỏi nhanh (nhiều lượt) và phân tích sâu (A/B/C, 8 bước) trong cùng một cuộc trò chuyện.
type Mode = 'quick' | 'A' | 'B' | 'C';
const MODE_INFO: Record<Mode, { label: string; hint: string }> = {
  quick: { label: 'Hỏi nhanh', hint: 'Trả lời ngắn từ tài liệu, nhớ ngữ cảnh các câu trước.' },
  A: { label: 'Vanilla RAG', hint: 'Điều kiện A: một lượt truy xuất, một lần sinh.' },
  B: { label: 'Multi-Agent cơ bản', hint: 'Điều kiện B: chia việc, chưa tối ưu.' },
  C: { label: 'Điều phối đầy đủ', hint: 'Điều kiện C: lập kế hoạch có kiểm tra, chuẩn hóa, tối ưu ngữ cảnh.' },
};
const STATUS_LABEL: Record<string, string> = { COMPLETE: 'Đủ bằng chứng', PARTIAL: 'Một phần', NO_EVIDENCE: 'Không có bằng chứng', FAILED: 'Thất bại' };
const PRESETS = [
  { label: 'Chống trừ tiền hai lần', text: 'Thiết kế cổng thanh toán không xử lý trùng bằng khóa idempotency' },
  { label: 'Phân quyền theo vai trò', text: 'Thiết kế phân quyền RBAC cho hệ thống nhiều tổ chức' },
  { label: 'Đồng bộ bằng Outbox', text: 'Mẫu Transactional Outbox để đồng bộ dữ liệu giữa các dịch vụ' },
];

// Nguồn đã hiện thành nút bên dưới nên bỏ dòng "Nguồn: [...]" trong thân câu trả lời.
const stripSources = (t: string) => t.replace(/\n?\s*Nguồn:\s*(\[[^\]]+\][,\s]*)+$/u, '').trim();
const isQuick = (run?: Cap1Run) => !!run?.events?.some((e: any) => e.stage === 'product_request_routing');
const citationsOf = (run?: Cap1Run) => [...new Set((run?.task_results || []).flatMap((r: any) => r.citations || []))] as string[];
const firstName = (name?: string) => name?.trim().split(/\s+/).slice(-1)[0];
const busy = (s: RobotState) => !['idle', 'happy', 'completed', 'error', 'sleeping', 'speaking'].includes(s);

interface WorkspaceProps {
  conversationId: string | null;
  onConversation: (id: string | null) => void;
  onChanged: () => void;
  userName?: string;
}

export const Workspace: React.FC<WorkspaceProps> = ({ conversationId, onConversation, onChanged, userName }) => {
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [runs, setRuns] = useState<Record<string, Cap1Run>>({});
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState<Mode>('quick');
  const [methodOpen, setMethodOpen] = useState(false);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<{ text: string; mode: Mode } | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ result: ModeExecutionResult; step: PipelineStep } | null>(null);
  const [agentsOf, setAgentsOf] = useState<string | null>(null);
  const [chunk, setChunk] = useState<{ id: string; source?: string; text?: string; error?: string } | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const skipLoad = useRef<string | null>(null);
  const { state, speechText, soundEnabled, toggleSound, poke, speak, setState } = useRobotAssistant();

  const load = useCallback(async (id: string) => {
    try {
      const conv = await getConversation(id);
      setMessages(conv.messages);
      const need = conv.messages.filter(m => m.run_id).map(m => m.run_id as string).slice(-30);
      const loaded = await Promise.all(need.map(r => getRawRun(r).catch(() => null)));
      setRuns(prev => ({ ...prev, ...Object.fromEntries(loaded.filter(Boolean).map(r => [r!.run_id, r!])) }));
    } catch (err: any) { setError(err.message); }
  }, []);

  useEffect(() => {
    setError(null); setAgentsOf(null);
    if (!conversationId) { setMessages([]); return; }
    if (skipLoad.current === conversationId) { skipLoad.current = null; return; }
    void load(conversationId); setOpen(true);
  }, [conversationId, load]);

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); }, [messages.length, pending]);
  useEffect(() => {
    if (!pending) return;
    const start = performance.now(); setElapsed(0);
    const t = window.setInterval(() => setElapsed(Math.floor((performance.now() - start) / 1000)), 1000);
    return () => window.clearInterval(t);
  }, [pending]);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);
  useEffect(() => {
    const el = inputRef.current; if (!el) return;
    el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [draft, open]);

  const expand = () => {
    if (open) return;
    setOpen(true);
    speak(`Chào ${firstName(userName) || 'bạn'}! Hỏi nhanh về tài liệu, hoặc chọn Phân tích để mình chia việc cho ba tác tử.`);
  };
  const pickMode = (m: Mode) => {
    setMode(m); setMethodOpen(false);
    speak(m === 'quick' ? 'Chế độ hỏi nhanh: mình trả lời ngắn và nhớ ngữ cảnh.' : `Phân tích sâu, ${MODE_INFO[m].hint}`);
    inputRef.current?.focus();
  };

  const send = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    setPending({ text, mode }); setDraft(''); setError(null);
    setState(mode === 'quick' ? 'searching' : 'decomposing');
    speak(mode === 'quick' ? 'Đang tìm trong tài liệu…' : 'Đang lập kế hoạch và chia việc cho các tác tử…');
    try {
      const run = mode === 'quick' ? await sendChat(text, conversationId) : await sendAnalysis(text, mode, conversationId);
      setRuns(prev => ({ ...prev, [run.run_id]: run }));
      if (run.conversation_id) {
        await load(run.conversation_id);
        if (run.conversation_id !== conversationId) { skipLoad.current = run.conversation_id; onConversation(run.conversation_id); }
      }
      onChanged();
      if (run.status === 'FAILED') { setState('error'); speak('Lượt này không hoàn thành. Mình đã ghi lý do trong câu trả lời.'); }
      else { setState('completed'); speak(`Xong sau ${((run.metrics?.latency_ms ?? 0) / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây.`); }
    } catch (err: any) {
      setError(err.message); setDraft(text); setState('error'); speak('Có lỗi khi gửi. Bạn thử lại nhé.');
    } finally { setPending(null); }
  };

  const showChunk = async (id: string) => {
    setChunk({ id });
    try { const c = await getChunk(id); setChunk({ id, source: c.source_name, text: c.text }); }
    catch (err: any) { setChunk({ id, error: err.message }); }
  };

  const fresh = messages.length === 0 && !pending;
  const busyNow = busy(state) || !!pending;

  const composer = (
    <form className={`ws-composer${open || !fresh ? ' is-open' : ''}${pending ? ' is-busy' : ''}`} onSubmit={send} onClick={expand}>
      {!(open || !fresh) ? (
        <button type="button" className="ws-launch" onClick={expand} aria-label="Mở khung hỏi đáp">
          <Sparkles size={16} /><span>Hỏi C27 về tài liệu của bạn…</span><kbd>Nhấn để bắt đầu</kbd>
        </button>
      ) : <>
        <textarea ref={inputRef} rows={fresh ? 3 : 1} value={draft} aria-label="Câu hỏi hoặc yêu cầu"
          placeholder={mode === 'quick' ? 'Hỏi bất kỳ điều gì trong kho tài liệu…' : 'Mô tả yêu cầu cần phân tích…'}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(); } }} />
        <div className="ws-bar">
          <div className="ws-seg" role="group" aria-label="Cách trả lời">
            <button type="button" className={mode === 'quick' ? 'is-on' : ''} onClick={() => pickMode('quick')} title={MODE_INFO.quick.hint}><Zap size={14} />Hỏi nhanh</button>
            <div className="ws-pop">
              <button type="button" className={mode !== 'quick' ? 'is-on' : ''} onClick={() => setMethodOpen(v => !v)} aria-expanded={methodOpen} aria-haspopup="menu" title="Phân tích sâu với ba tác tử">
                <Microscope size={14} />{mode === 'quick' ? 'Phân tích' : `Phân tích · ${mode}`}<ChevronDown size={13} />
              </button>
              {methodOpen && <div className="pop is-up-left" role="menu">
                {(['C', 'B', 'A'] as Mode[]).map(m => (
                  <button key={m} type="button" role="menuitem" className="pop-item" onClick={() => pickMode(m)}>
                    <b className={`mode-key${m === 'C' ? ' is-a' : ''}`}>{m}</b>
                    <span className="pop-text"><b>{MODE_INFO[m].label}</b><small>{MODE_INFO[m].hint}</small></span>
                  </button>
                ))}
              </div>}
            </div>
          </div>
          <button type="submit" className="send" disabled={!!pending || !draft.trim()} aria-label="Gửi">{pending ? <span className="spin" /> : <ArrowUp size={18} />}</button>
        </div>
      </>}
    </form>
  );

  return (
    <main className={`mn ws${fresh ? ' is-fresh' : ''}`}>
      <div className="ws-top">
        <button type="button" className={`ws-bot${busyNow ? ' is-busy' : ''}`} onClick={poke} aria-label="Chạm vào Trợ lý C27" title="Chạm để C27 phản hồi">
          <AssistantRobot size={fresh ? 88 : 44} interactive colorConfig={{ shell: '#1d344a', trim: '#d5dde6', screen: state === 'error' ? '#ff8a8a' : busyNow ? '#ffd27a' : '#8fdcff' }} />
        </button>
        <p className="ws-say" aria-live="polite" key={speechText}>{speechText}</p>
        <button type="button" onClick={toggleSound} className="icon-btn is-sm ws-sound" aria-label={soundEnabled ? 'Tắt âm thanh' : 'Bật âm thanh'}>{soundEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}</button>
      </div>

      {fresh ? (
        <div className="ws-hero">
          <h1>Chào {firstName(userName) || 'bạn'}, cần tìm gì hôm nay?</h1>
          {composer}
          <div className={`ws-chips${open ? ' is-in' : ''}`}>
            {PRESETS.map(p => <button key={p.label} type="button" onClick={() => { setOpen(true); setDraft(p.text); setMode('C'); speak('Đã điền ví dụ. Nhấn gửi để phân tích.'); }}>{p.label}</button>)}
          </div>
        </div>
      ) : (
        <div className="ws-thread">
          <div className="ws-msgs">
            {messages.map(m => {
              if (m.role === 'USER') return <div key={m.message_id} className="ws-msg is-user"><p>{m.content}</p></div>;
              const run = m.run_id ? runs[m.run_id] : undefined;
              const quick = isQuick(run);
              const cites = citationsOf(run);
              const failed = run?.status === 'FAILED';
              const hasAgents = !quick && (run?.task_results?.length ?? 0) > 0;
              const result = run ? adaptRun(run) : null;
              return (
                <article key={m.message_id} className="ws-msg is-bot">
                  <header>
                    <span className="ws-tag">{quick ? <><Zap size={12} />Hỏi nhanh</> : <><Microscope size={12} />{CONDITION_LABEL[run?.condition] ?? 'Phân tích'}</>}</span>
                    {run?.status && <span className={`cht-status is-${String(run.status).toLowerCase()}`}>{STATUS_LABEL[run.status] ?? run.status}</span>}
                  </header>
                  <div className="md"><Markdown text={failed ? explainFailure(m.content) : stripSources(answerText(m.content))} /></div>
                  {cites.length > 0 && <div className="cht-cites"><BookOpen size={13} />{cites.map(c => <button key={c} onClick={() => showChunk(c)} title="Xem đoạn tài liệu">{c.split('_').slice(-2).join('_')}</button>)}</div>}
                  {run && <footer>
                    <span className="ws-meta">{((run.metrics?.input_tokens ?? 0) + (run.metrics?.output_tokens ?? 0)).toLocaleString('vi-VN')} token · {((run.metrics?.latency_ms ?? 0) / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây</span>
                    <button type="button" onClick={() => result && setTrace({ result, step: PIPELINE_STEPS[0] })}><Footprints size={13} />8 bước</button>
                    {hasAgents && <button type="button" aria-expanded={agentsOf === run.run_id} onClick={() => setAgentsOf(agentsOf === run.run_id ? null : run.run_id)}><Users size={13} />Theo tác tử</button>}
                  </footer>}
                  {hasAgents && agentsOf === run!.run_id && <div className="ws-agents">
                    {result!.agent_results.map((a, i) => <section key={i}><h4>{a.agent_role.replace('Agent', '')} · {a.subtask_title}</h4><div className="md"><Markdown text={a.content} /></div></section>)}
                  </div>}
                </article>
              );
            })}
            {pending && <>
              <div className="ws-msg is-user"><p>{pending.text}</p></div>
              <div className="ws-msg is-bot is-wait"><span className="ws-dots"><i /><i /><i /></span>{pending.mode === 'quick' ? 'Đang tìm trong tài liệu' : 'Các tác tử đang làm việc'} · {elapsed}s</div>
            </>}
            <div ref={endRef} />
          </div>
          {error && <p className="note is-error" role="alert">{error}</p>}
          {composer}
        </div>
      )}

      {trace && <NodeTraceModal isOpen step={trace.step} result={trace.result} onClose={() => setTrace(null)} onSelectStep={s => setTrace({ ...trace, step: s })} />}
      {chunk && <StudioModal labelId="ws-chunk" size="md" icon={<BookOpen size={18} />} title="Đoạn tài liệu được trích" subtitle={chunk.source || chunk.id} onClose={() => setChunk(null)}
        footer={<button className="btn btn-dark" onClick={() => setChunk(null)}>Đóng</button>}>
        {chunk.error ? <p className="note is-error">{chunk.error}</p> : chunk.text == null ? <p className="muted-line"><span className="spin is-dark" />Đang tải…</p> : <pre className="chunk-pre">{chunk.text}</pre>}
      </StudioModal>}
    </main>
  );
};
