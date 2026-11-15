import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUp, BookOpen, ChevronDown, Clock, Coins, FileText, FolderOpen, Inbox, ListChecks, MessageSquareText, Microscope, Sparkles, Upload, Users, Volume2, VolumeX, Zap } from 'lucide-react';
import { ConversationMessage, getChunk, getConversation, getRawRun, sendAnalysis, sendChat, explainFailure } from '../services/api';
import { adaptRun, answerText, Cap1Run, CONDITION_LABEL } from '../services/adapt';
import { Markdown } from '../utils/markdown';
import { AssistantRobot } from './robot/AssistantRobot';
import { useRobotAssistant } from './robot/RobotContext';
import { RobotState } from './robot/robotEngine';
import { PIPELINE_STEPS, PipelineStep } from './ExecutionFlowGraph';
import { NodeTraceModal } from './NodeTraceModal';
import { SourceChips } from './SourceChips';
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
// Viết dạng câu hỏi để CAP1 đi đường hỏi đáp trực tiếp (câu mệnh lệnh bị chuyển sang lập kế hoạch nhiều bước).
const PRESETS = [
  { label: 'Tóm tắt ý chính', text: 'Tài liệu nói về những ý chính nào?' },
  { label: 'Quy trình gồm bước nào?', text: 'Quy trình này gồm những bước nào, ai phụ trách từng bước?' },
  { label: 'Điều kiện, hạn mức', text: 'Có những điều kiện, hạn mức hoặc thời hạn nào cần lưu ý?' },
  { label: 'Ai được phê duyệt?', text: 'Ai có quyền phê duyệt việc này?' },
  { label: 'Giải thích thuật ngữ', text: 'Những thuật ngữ quan trọng trong tài liệu có nghĩa là gì?' },
  { label: 'Lỗi thường gặp', text: 'Lỗi thường gặp nào cần lưu ý?' },
]

// Nguồn đã hiện thành nút bên dưới nên bỏ dòng "Nguồn: [...]" trong thân câu trả lời.
const stripSources = (t: string) => t.replace(/\n?\s*Nguồn:\s*(\[[^\]]+\][,\s]*)+$/u, '').trim();
const isQuick = (run?: Cap1Run) => !!run?.events?.some((e: any) => e.stage === 'product_request_routing');
const citationsOf = (run?: Cap1Run) => [...new Set((run?.task_results || []).flatMap((r: any) => r.citations || []))] as string[];
// Dòng chỉ số: "8,4 giây" / "1 phút 3 giây"; token rút gọn "5,4k" (số đầy đủ nằm trong tooltip).
const fmtSeconds = (ms: number) => {
  const total = ms / 1000;
  if (total < 60) return `${total.toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây`;
  const m = Math.floor(total / 60), sec = Math.round(total - m * 60);
  return sec === 60 ? `${m + 1} phút` : `${m} phút ${sec} giây`;
};
const fmtTokens = (n: number) => n >= 1000 ? `${(n / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })}k` : String(n);
const sourceCount = (run?: Cap1Run) => Array.isArray(run?.sources) && run!.sources.length ? run!.sources.length : citationsOf(run).length;
const firstName = (name?: string) => name?.trim().split(/\s+/).slice(-1)[0];
const busy = (s: RobotState) => !['idle', 'happy', 'completed', 'error', 'sleeping', 'speaking'].includes(s);

// Lời thoại hiện dần từng chữ; tôn trọng giảm chuyển động.
function useTyped(text: string) {
  const [shown, setShown] = useState(text);
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setShown(text); return; }
    let i = 0; setShown('');
    const t = window.setInterval(() => { i += 2; setShown(text.slice(0, i)); if (i >= text.length) window.clearInterval(t); }, 18);
    return () => window.clearInterval(t);
  }, [text]);
  return shown;
}

interface WorkspaceProps {
  workspaceId: number | string;
  conversationId: string | null;
  onConversation: (id: string | null) => void;
  onChanged: () => void;
  userName?: string;
  /** Số liệu kho đang mở và lối tắt cho màn hình đầu. */
  docs?: { id?: number | string; source_file: string; chunks_count: number }[];
  docCount?: number;
  chunkCount?: number;
  modelOk?: boolean;
  workspaceName?: string;
  recent?: { conversation_id: string; title: string; updated_at: string }[];
  onSeed?: () => void;
  onUploadFile?: (file: File) => void;
}

export const Workspace: React.FC<WorkspaceProps> = ({ workspaceId, conversationId, onConversation, onChanged, userName, docs = [], docCount = 0, chunkCount = 0, modelOk, workspaceName, recent = [], onSeed, onUploadFile }) => {
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
  const fileRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const closedH = useRef(0);
  const endRef = useRef<HTMLDivElement>(null);
  const skipLoad = useRef<string | null>(null);
  const { state, speechText, soundEnabled, toggleSound, speak, setState } = useRobotAssistant();
  const typed = useTyped(speechText);

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

  useLayoutEffect(() => {
    const el = formRef.current;
    if (!open || !el || !closedH.current || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    el.animate([{ height: `${closedH.current}px`, overflow: 'hidden' }, { height: `${el.offsetHeight}px`, overflow: 'hidden' }],
      { duration: 650, easing: 'cubic-bezier(.45,0,.2,1)' });
    closedH.current = 0;
  }, [open]);

  const expand = () => {
    if (open) return;
    closedH.current = formRef.current?.offsetHeight ?? 0;
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
      const run = mode === 'quick' ? await sendChat(text, conversationId, workspaceId) : await sendAnalysis(text, mode, conversationId, workspaceId);
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
    <form ref={formRef} className={`ws-composer${open || !fresh ? ' is-open' : ''}${pending ? ' is-busy' : ''}`} onSubmit={send} onClick={expand}>
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
        <div className={`ws-bot${busyNow ? ' is-busy' : ''}`} aria-label="Chạm vào Trợ lý C27" title="Chạm để C27 phản hồi">
          <AssistantRobot size={fresh ? 132 : 44} interactive colorConfig={{ shell: '#1d344a', trim: '#d5dde6', screen: state === 'error' ? '#ff8a8a' : busyNow ? '#ffd27a' : '#8fdcff' }} />
        </div>
        <p className="ws-say" aria-live="polite"><span className="sr">{speechText}</span><span aria-hidden="true">{typed}<i className="ws-caret" /></span></p>
        <button type="button" onClick={toggleSound} className="icon-btn is-sm ws-sound" aria-label={soundEnabled ? 'Tắt âm thanh' : 'Bật âm thanh'}>{soundEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}</button>
      </div>

      {fresh ? (
        <div className="ws-hero">
          <div className="ws-glow" aria-hidden="true"><i /><i /><i /></div>
          <h1>Chào {firstName(userName) || 'bạn'}, <span>cần tìm gì hôm nay?</span></h1>
          <div className="ws-stats" aria-label="Tình trạng kho">
            <span><FolderOpen size={14} />{workspaceName || 'Kho tài liệu'}</span>
            <span><FileText size={14} />{docCount} tài liệu · {chunkCount} đoạn</span>
            <span className={modelOk ? 'is-ok' : 'is-warn'}><i />{modelOk ? 'Mô hình sẵn sàng' : 'Chưa kết nối mô hình'}</span>
          </div>
          {composer}
          <div className={`ws-chips${open ? ' is-in' : ''}`}>
            {PRESETS.map(p => <button key={p.label} type="button" onClick={() => { setOpen(true); setDraft(p.text); setMode('quick'); inputRef.current?.focus(); speak('Đã điền câu hỏi. Bạn sửa thêm hoặc nhấn gửi nhé.'); }}>{p.label}</button>)}
          </div>
          {docCount === 0 && onSeed && <div className="ws-empty-kb"><Inbox size={18} /><span>Kho đang trống.</span><button type="button" onClick={onSeed}>Dùng bộ tài liệu mẫu</button><button type="button" onClick={() => fileRef.current?.click()}>Tải tài liệu lên</button></div>}
          {docs.length > 0 && <div className="ws-docs">
            <p>Tài liệu trong không gian <small>Bấm để hỏi về tài liệu</small></p>
            <div className="ws-docs-row">
              {docs.slice(0, 5).map((d, i) => (
                <button key={d.id ?? d.source_file} type="button" style={{ animationDelay: `${0.06 * i}s` }} title={d.source_file}
                  onClick={() => { closedH.current = open ? 0 : formRef.current?.offsetHeight ?? 0; setOpen(true); setMode('quick'); setDraft(`Nội dung chính của tài liệu ${d.source_file} là gì?`); speak(`Mình sẽ đọc ${d.source_file}. Nhấn gửi nhé.`); }}>
                  <FileText size={16} /><span>{d.source_file}</span><small>{d.chunks_count} đoạn</small>
                </button>
              ))}
              <button type="button" className="is-add" onClick={() => fileRef.current?.click()}><Upload size={16} /><span>Thêm tài liệu</span></button>
            </div>
          </div>}
          {recent.length > 0 && <div className="ws-recent">
            <p>Tiếp tục</p>
            {recent.slice(0, 3).map(c => (
              <button key={c.conversation_id} type="button" onClick={() => onConversation(c.conversation_id)}>
                <MessageSquareText size={15} /><span>{c.title || 'Không tên'}</span><ArrowRight size={14} />
              </button>
            ))}
          </div>}
          <input ref={fileRef} type="file" hidden accept=".pdf,.md,.markdown,.sql,.txt"
            onChange={e => { const f = e.target.files?.[0]; if (f) onUploadFile?.(f); e.target.value = ''; }} />
        </div>
      ) : (
        <div className="ws-thread">
          <div className="ws-msgs">
            {messages.map(m => {
              if (m.role === 'USER') return <div key={m.message_id} className="ws-msg is-user"><p>{m.content}</p></div>;
              const run = m.run_id ? runs[m.run_id] : undefined;
              const quick = isQuick(run);
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
                  <SourceChips run={run} />
                  {run && <footer>
                    <span className="ws-meta">
                      <span title="Thời gian xử lý"><Clock size={13} />{fmtSeconds(run.metrics?.latency_ms ?? 0)}</span>
                      <span title={`${((run.metrics?.input_tokens ?? 0) + (run.metrics?.output_tokens ?? 0)).toLocaleString('vi-VN')} token (vào ${(run.metrics?.input_tokens ?? 0).toLocaleString('vi-VN')} · ra ${(run.metrics?.output_tokens ?? 0).toLocaleString('vi-VN')})`}><Coins size={13} />{fmtTokens((run.metrics?.input_tokens ?? 0) + (run.metrics?.output_tokens ?? 0))}</span>
                      {sourceCount(run) > 0 && <span title="Số đoạn tài liệu được trích"><FileText size={13} />{sourceCount(run)} nguồn</span>}
                    </span>
                    <button type="button" onClick={() => result && setTrace({ result, step: PIPELINE_STEPS[0] })}><ListChecks size={13} />8 bước</button>
                    {hasAgents && <button type="button" aria-expanded={agentsOf === run.run_id} onClick={() => setAgentsOf(agentsOf === run.run_id ? null : run.run_id)}><Users size={13} />Theo agent</button>}
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
