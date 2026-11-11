import { metric, percent } from '../utils/measurement';
import { groupAgentResults } from '../utils/agentResults';
import { TaskPlanTrace } from './TaskPlanTrace';
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { ArrowUp, Check, Copy, Volume2, VolumeX, ChevronDown, Clock, ShieldCheck, CornerDownLeft, CreditCard, Building2, GitMerge, CircleCheck, History } from 'lucide-react';
import { ModeExecutionResult, ExecutionMode } from '../types';
import { AssistantRobot } from './robot/AssistantRobot';
import { useRobotAssistant } from './robot/RobotContext';
import { RobotState } from './robot/robotEngine';
import { PIPELINE_STEPS, PipelineStep, stepEvents } from './ExecutionFlowGraph';
import { NodeTraceModal } from './NodeTraceModal';
import { MODES, useDismiss } from './Header';
import { Markdown } from '../utils/markdown';
import { serverDate } from '../utils/time';

interface CenterCanvasProps {
  onAnalyze: (query: string) => Promise<void>;
  result: ModeExecutionResult | null;
  isAnalyzing: boolean;
  mode: ExecutionMode;
  onModeChange?: (m: ExecutionMode) => void;
  userName?: string;
  /** Lượt chạy cũ đang mở lại từ Lịch sử trò chuyện. */
  viewing?: { id: number; query: string; createdAt: string } | null;
  onNewChat?: () => void;
}

type Tab = 'database' | 'api' | 'security' | 'shared_brief' | 'full_report';

const PRESETS = [
  { Icon: CreditCard, tone: 'blue', title: 'Cổng thanh toán & Idempotency Key', desc: 'Xử lý Stripe Webhook, cơ chế Idempotency Key, chống duplicate request và khóa lạc quan (Optimistic Locking).' },
  { Icon: Building2, tone: 'violet', title: 'Đa khách thuê & phân quyền theo hàng', desc: 'Thiết kế phân quyền RBAC, cách ly dữ liệu giữa các tổ chức với PostgreSQL Row-Level Security và JWT Claims.' },
  { Icon: GitMerge, tone: 'teal', title: 'Đồng bộ phân tán bằng Outbox', desc: 'Mẫu thiết kế Transactional Outbox, đồng bộ CDC với Kafka/RabbitMQ và xử lý Dead-Letter Queue.' },
];
const AGENTS = [
  { key: 'database' as const, role: 'DatabaseAgent', label: 'Dữ liệu', tone: 'db' },
  { key: 'api' as const, role: 'APIAgent', label: 'API', tone: 'api' },
  { key: 'security' as const, role: 'SecurityAgent', label: 'Bảo mật', tone: 'sec' },
];

function statusOf(s: RobotState): { label: string; tone: 'ok' | 'busy' | 'bad' } {
  switch (s) {
    case 'receiving': case 'decomposing': case 'thinking': case 'assigning': case 'retrieving': case 'searching': case 'executing': case 'working': case 'synthesizing': return { label: 'Đang làm việc', tone: 'busy' };
    case 'error': return { label: 'Có lỗi', tone: 'bad' };
    default: return { label: 'Sẵn sàng', tone: 'ok' };
  }
}

// Lời chào theo giờ trong ngày, chỉ dùng tên gọi (từ cuối của họ tên).
function greeting(name?: string) {
  const h = new Date().getHours();
  const part = h < 11 ? 'Chào buổi sáng' : h < 14 ? 'Chào buổi trưa' : h < 18 ? 'Chào buổi chiều' : 'Chào buổi tối';
  return { part, first: name?.trim().split(/\s+/).slice(-1)[0] };
}

export const CenterCanvas: React.FC<CenterCanvasProps> = ({ onAnalyze, result, isAnalyzing, mode, onModeChange, userName, viewing, onNewChat }) => {
  const [query, setQuery] = useState('');
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<Tab>('full_report');
  const [traceStep, setTraceStep] = useState<PipelineStep | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [modeOpen, setModeOpen] = useState(false);
  const closeMode = useCallback(() => setModeOpen(false), []);
  const modeRef = useDismiss(modeOpen, closeMode);
  const resultsRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { state, speechText, soundEnabled, toggleSound, poke, lookAtElement, speak } = useRobotAssistant();

  // Đồng hồ chờ đo ở trình duyệt; API chưa có tiến độ từng bước nên không hiển thị phần trăm.
  useEffect(() => {
    if (!isAnalyzing) return;
    const start = performance.now();
    setElapsed(0);
    const t = window.setInterval(() => setElapsed(Math.floor((performance.now() - start) / 1000)), 1000);
    return () => window.clearInterval(t);
  }, [isAnalyzing]);
  useEffect(() => {
    if (!result) return;
    setTab('full_report');
    resultsRef.current?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }, [result]);
  // Mở lại lượt cũ: đưa yêu cầu cũ vào ô soạn để người dùng sửa và chạy lại nếu muốn.
  useEffect(() => { if (viewing) setQuery(viewing.query); }, [viewing?.id]);
  // Ô soạn tự giãn theo nội dung.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 320)}px`;
  }, [query]);

  const openStep = (step: PipelineStep) => { setTraceStep(step); setTraceOpen(true); speak(`Giai đoạn ${step.stepNumber}: ${step.title}. ${step.scientificRole}`); };
  const usePreset = (text: string) => { setQuery(text); inputRef.current?.focus(); lookAtElement('architecture-request-input', 2); speak('Đã nạp kịch bản mẫu. Nhấn gửi để bắt đầu điều phối.'); };
  const submit = async (e?: React.FormEvent) => { e?.preventDefault(); if (!query.trim() || isAnalyzing) return; await onAnalyze(query); };
  const copy = (text: string) => { if (!text) return; navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); };

  const st = statusOf(state);
  const groups = { database: groupAgentResults(result?.agent_results, 'DatabaseAgent'), api: groupAgentResults(result?.agent_results, 'APIAgent'), security: groupAgentResults(result?.agent_results, 'SecurityAgent') };
  const text = tab === 'shared_brief' ? result?.shared_brief || '' : tab === 'full_report' ? result?.final_answer || '' : groups[tab]?.content || '';
  const m = MODES[mode];
  const clock = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;
  const fresh = !result && !isAnalyzing;

  return (
    <main className="mn">
      <div className="mn-col">
        <div className="mn-bar">
          <div className={`asst is-${st.tone}`}>
            <button type="button" className="asst-bot" onClick={poke} aria-label="Chạm vào Trợ lý C27" title="Chạm để C27 phản hồi">
              <AssistantRobot size={76} interactive colorConfig={{ shell: '#1d344a', trim: '#d5dde6', screen: state === 'error' ? '#ff8a8a' : st.tone === 'busy' ? '#ffd27a' : '#8fdcff' }} />
            </button>
            <div className="asst-text" aria-live="polite">
              <span className="asst-name">C27 <i />{st.label}</span>
              <p>{speechText}</p>
            </div>
            <button type="button" onClick={toggleSound} className="icon-btn is-sm" aria-label={soundEnabled ? 'Tắt âm thanh phản hồi' : 'Bật âm thanh phản hồi'} title={soundEnabled ? 'Tắt âm thanh' : 'Bật âm thanh'}>{soundEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}</button>
          </div>
        </div>

        {fresh && <div className="mn-hero">
          <p className="mn-greet">{greeting(userName).part}{greeting(userName).first && <>, <span>{greeting(userName).first}</span></>}</p>
          <h1>Bạn muốn phân tích điều gì?</h1>
          <p>Mô tả một yêu cầu phần mềm. Ba tác tử Dữ liệu, API và Bảo mật sẽ chia việc và đọc tài liệu trong kho của bạn.</p>
        </div>}

        <form className={`composer${isAnalyzing ? ' is-busy' : ''}`} onSubmit={submit}>
          <textarea
            ref={inputRef}
            id="architecture-request-input"
            aria-label="Yêu cầu kỹ thuật cần phân rã và điều phối"
            rows={fresh ? 3 : 2}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void submit(); } }}
            placeholder="Ví dụ: Thiết kế cổng thanh toán không xử lý trùng và có kiểm soát quyền truy cập"
          />
          <div className="composer-bar">
            <div className="sb-pop" ref={modeRef}>
              <button type="button" className="mode-btn" onClick={() => setModeOpen(!modeOpen)} aria-expanded={modeOpen} aria-haspopup="menu" disabled={!onModeChange} title="Phương pháp điều phối">
                <b className={m.key === 'C' ? 'is-a' : ''}>{m.key}</b>{m.title}<ChevronDown size={14} />
              </button>
              {modeOpen && onModeChange && (
                <div className="pop is-up-left" role="menu">
                  <p className="pop-label">Phương pháp điều phối</p>
                  {(Object.keys(MODES) as ExecutionMode[]).map(k => (
                    <button key={k} role="menuitemradio" aria-checked={mode === k} className="pop-item is-mode" onClick={() => { onModeChange(k); setModeOpen(false); }}>
                      <b className={`mode-key${MODES[k].key === 'C' ? ' is-a' : ''}`}>{MODES[k].key}</b>
                      <span className="pop-text"><b>{MODES[k].title} <em>{MODES[k].badge}</em></b><small>{MODES[k].desc}</small></span>
                      {mode === k && <Check size={15} className="pop-check" />}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <span className="composer-hint"><CornerDownLeft size={13} />Ctrl + Enter</span>
            <button id="btn-submit-orchestration" type="submit" className="send" disabled={isAnalyzing || !query.trim()} aria-label="Phân rã và điều phối">
              {isAnalyzing ? <span className="spin" /> : <ArrowUp size={18} />}
            </button>
          </div>
        </form>

        {fresh && <div className="presets">
          {PRESETS.map(p => (
            <button key={p.title} className="preset" onClick={() => usePreset(p.desc)}>
              <i className={`preset-ic is-${p.tone}`}><p.Icon size={15} /></i><b>{p.title}</b><span>{p.desc}</span>
            </button>
          ))}
        </div>}

        {isAnalyzing && (
          <section className="running" aria-live="polite">
            <div className="running-top"><span className="running-dots"><i /><i /><i /></span><b>Ba tác tử đang làm việc</b><span className="running-clock"><Clock size={14} />{clock}</span></div>
            <p>Đang chờ máy chủ trả kết quả. Hệ thống chưa báo tiến độ từng bước, nên Studio không hiển thị phần trăm.</p>
            <div className="running-lines"><i /><i /><i /></div>
          </section>
        )}

        {result && !isAnalyzing && (
          <div ref={resultsRef} className="out">
            {viewing && <div className="out-replay" role="status">
              <History size={15} />
              <span>Đang xem lại lượt chạy lúc <b>{serverDate(viewing.createdAt).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' })}</b>. Đây là kết quả đã lưu, không chạy lại.</span>
              {onNewChat && <button type="button" className="btn btn-ghost" onClick={() => { setQuery(''); onNewChat(); inputRef.current?.focus(); }}>Yêu cầu mới</button>}
            </div>}
            <p className="out-done"><CircleCheck size={16} />Hoàn tất sau {(result.latency_ms / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây · {result.agent_results.length} đầu ra tác tử</p>
            <div className="out-head">
              <span className="out-label">Kết quả · {result.mode_display_name}</span>
              <dl className="out-stats">
                <div><dt>Token</dt><dd>{result.total_tokens.toLocaleString('vi-VN')}</dd></div>
                <div><dt>Thời gian</dt><dd>{(result.latency_ms / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây</dd></div>
                <div><dt>Đoạn truy xuất</dt><dd>{result.retrieved_chunks_count}</dd></div>
                <div><dt>Tiết kiệm</dt><dd className={result.tokens_saved == null ? 'is-muted' : ''}>{metric(result.tokens_saved, ' token')}</dd></div>
              </dl>
            </div>

            <div className="tabs" role="tablist" aria-label="Đầu ra">
              <button role="tab" aria-selected={tab === 'full_report'} className={tab === 'full_report' ? 'is-on' : ''} onClick={() => setTab('full_report')}>Báo cáo tổng hợp</button>
              {AGENTS.map(a => <button key={a.key} role="tab" aria-selected={tab === a.key} className={tab === a.key ? 'is-on' : ''} onClick={() => setTab(a.key)}><i className={`dot is-${a.tone}`} />{a.label}</button>)}
              {result.shared_brief && <button role="tab" aria-selected={tab === 'shared_brief'} className={tab === 'shared_brief' ? 'is-on' : ''} onClick={() => setTab('shared_brief')}>Shared Brief</button>}
              <button className="tabs-copy" onClick={() => copy(text)}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Đã sao chép' : 'Sao chép'}</button>
            </div>

            <article className="doc" key={tab}>
              {tab === 'full_report' && <Markdown text={result.final_answer || 'Chưa có báo cáo.'} />}
              {(tab === 'database' || tab === 'api' || tab === 'security') && (groups[tab]
                ? <><p className="doc-meta">{groups[tab]!.subtask_title} · {groups[tab]!.latency_ms.toLocaleString('vi-VN')} ms · {groups[tab]!.tokens_used.toLocaleString('vi-VN')} token</p><Markdown text={groups[tab]!.content} /></>
                : <p className="doc-empty">Tác tử {AGENTS.find(a => a.key === tab)?.role} không tham gia lượt chạy này.</p>)}
              {tab === 'shared_brief' && <><p className="doc-meta">Câu nguyên văn dùng chung · tiết kiệm {metric(result.tokens_saved, ' token')}</p><Markdown text={result.shared_brief || 'Không có thực thể trùng lặp.'} /></>}
            </article>

            {result.brief_verification && (
              <section className="check" data-testid="brief-verification">
                <h2><ShieldCheck size={16} />Kiểm chứng Shared Brief</h2>
                <ul>
                  <li><span>Nén</span>{result.brief_verification.compressed ? `Có, bỏ ${result.brief_verification.dropped_sentences}/${result.brief_verification.total_sentences ?? '?'} câu` : 'Không nén, giữ nguyên toàn bộ'}</li>
                  <li className={result.brief_verification.verification.ok ? 'is-ok' : 'is-bad'}><span>Nguồn</span>{result.brief_verification.verification.ok ? 'Mọi câu khớp nguyên văn' : `${result.brief_verification.verification.issues.length} lỗi trích dẫn`}</li>
                  <li className={result.brief_verification.evidence.missing_evidence.length ? 'is-warn' : 'is-ok'}><span>Bằng chứng</span>{result.brief_verification.evidence.missing_evidence.length ? `Thiếu ở ${result.brief_verification.evidence.missing_evidence.join(', ')}` : 'Không nhiệm vụ nào thiếu'}</li>
                  <li><span>Độ phủ</span>{percent(result.brief_verification.evidence.task_coverage)}</li>
                </ul>
              </section>
            )}
            <TaskPlanTrace result={result} />
          </div>
        )}

        <section className="steps">
          <div className="steps-head"><h2>Một lượt chạy gồm 8 bước</h2><span>Bấm vào từng bước để xem chi tiết</span></div>
          <ol className="steps-list">
            {PIPELINE_STEPS.map(step => (
              <li key={step.id}>
                {(() => { const ran = !!result && !isAnalyzing && stepEvents(result.raw, step).length > 0; const skipped = !!result && !isAnalyzing && !ran; return (
                <button onClick={() => openStep(step)} aria-label={`Xem bước ${step.stepNumber}: ${step.shortTitle}${skipped ? ' (không diễn ra trong lượt này)' : ''}`} className={ran ? 'is-done' : skipped ? 'is-skip' : ''}>
                  <span className="steps-n">{ran ? <Check size={13} /> : step.stepNumber}</span>
                  <span className="steps-t">{step.shortTitle}</span>
                </button>); })()}
              </li>
            ))}
          </ol>
        </section>
      </div>

      <NodeTraceModal step={traceStep} isOpen={traceOpen} onClose={() => { setTraceOpen(false); setTraceStep(null); }} result={result} onSelectStep={openStep} />
    </main>
  );
};
