import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import gsap from 'gsap';
import { useGSAP } from '@gsap/react';
import {
  AlertTriangle,
  ArrowDown,
  ArrowUpRight,
  CheckCheck,
  ChevronRight,
  FileText,
  FilterX,
  MessageSquareText,
  Pin,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { AGENT_PROFILES } from './agents';
import { AgentRobotAvatar, AgentRoleLogo } from './AgentRobotAvatar';
import type {
  OfficeChatAttachment,
  OfficeChatKind,
  OfficeChatMessage,
  OfficeChatPhase,
} from './liveDirector';
import type { AgentId, ComplexityScenario } from './types';

gsap.registerPlugin(useGSAP);

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
}

export interface OfficeChatFeedProps {
  question?: string;
  mode: 'live' | 'replay' | 'demo';
  variant: 'floating-side' | 'full-tab';
  messages: OfficeChatMessage[];
  activeAgents: AgentId[];
  /** Danh sách Agent đang thực sự làm việc tại thời điểm này (đồng bộ 1:1 với luồng nối 3D) */
  activeWorkers?: AgentId[];
  leadActor?: AgentId | null;
  activeWorkLabel: string | null;
  waitingSec: number | null;
  finished: boolean;
  failed: boolean;
  onFocusAgent: (id: AgentId) => void;
  onClose?: () => void;
  title?: string;
}

const PHASE_LABEL_VI: Record<OfficeChatPhase, string> = {
  intake: 'Tiếp nhận & Điều phối',
  work: 'Tra cứu & Thực thi',
  review: 'Kiểm định chất lượng',
  done: 'Hoàn tất & Bàn giao',
};

const SHORT_LABEL_VI: Record<AgentId, string> = {
  orchestrator: 'Điều phối',
  rag: 'RAG',
  analyst: 'Số liệu',
  reviewer: 'Kiểm định',
  integrator: 'Tổng hợp',
  software: 'CNTT',
  business: 'Kinh doanh',
  marketing: 'Marketing',
  hr: 'Nhân sự',
  finance: 'Tài chính',
  education: 'Nghiên cứu',
};

function recipientLabel(to: AgentId | 'all' | 'user'): string {
  if (to === 'all') return 'cả nhóm';
  if (to === 'user') return 'người dùng';
  return AGENT_PROFILES[to]?.shortName ?? to;
}

function recipientAccent(to: AgentId | 'all' | 'user'): string {
  if (to === 'all') return '#64748b';
  if (to === 'user') return '#6366f1';
  return AGENT_PROFILES[to]?.accentHex ?? '#475569';
}

function isRightSideAgent(id: AgentId): boolean {
  return id === 'orchestrator' || id === 'integrator';
}

function AttachmentGlyph({ icon }: { icon: OfficeChatAttachment['icon'] }) {
  switch (icon) {
    case 'doc':
      return <FileText size={15} />;
    case 'qc_ok':
      return <ShieldCheck size={15} />;
    case 'qc_warn':
      return <AlertTriangle size={15} />;
    case 'done':
      return <Sparkles size={15} />;
    default:
      return <FileText size={15} />;
  }
}

/** Chuyển các bước đã qua của kịch bản Minh họa thành cuộc trò chuyện nhóm tự nhiên. */
export function buildDemoChatFeed(
  scenario: ComplexityScenario | null,
  stageIndex: number,
): OfficeChatMessage[] {
  if (!scenario || !scenario.stages.length) return [];
  const limit = Math.min(scenario.stages.length - 1, Math.max(0, stageIndex));
  const out: OfficeChatMessage[] = [];
  for (let i = 0; i <= limit; i += 1) {
    const st = scenario.stages[i];
    const from: AgentId = st.handoff?.from ?? st.dispatchTargets?.from ?? st.leadActor;
    let to: AgentId | 'all' | 'user' = 'all';
    if (st.handoff) to = st.handoff.to;
    else if (st.dispatchTargets && st.dispatchTargets.toList.length === 1) to = st.dispatchTargets.toList[0];
    else if (i === scenario.stages.length - 1 && st.leadActor === 'integrator') to = 'user';

    const isLast = i === scenario.stages.length - 1;
    let kind: OfficeChatKind = 'work';
    let phase: OfficeChatPhase = 'work';
    if (isLast) {
      kind = 'done';
      phase = 'done';
    } else if (from === 'rag') {
      kind = 'rag';
      phase = 'work';
    } else if (from === 'reviewer') {
      kind = 'review';
      phase = 'review';
    } else if (from === 'orchestrator') {
      kind = 'plan';
      phase = 'intake';
    }

    let attachment: OfficeChatAttachment | undefined;
    if (from === 'rag') {
      attachment = { icon: 'doc', title: st.handoff?.label || 'Tập tài liệu RAG liên quan', subtitle: 'Hồ sơ trích xuất' };
    } else if (from === 'reviewer') {
      attachment = { icon: 'qc_ok', title: 'Đạt kiểm định chất lượng (QC)', subtitle: 'Số liệu khớp nguồn' };
    } else if (isLast) {
      attachment = { icon: 'done', title: 'Báo cáo hoàn chỉnh đã gửi khách' };
    }

    out.push({
      id: `demo-${scenario.id}-${st.id}`,
      from,
      to,
      kind,
      phase,
      mood: isLast || from === 'reviewer' ? 'happy' : 'focus',
      text: st.detail || st.headline,
      badge: isLast ? 'Hoàn tất' : undefined,
      attachment,
    });
  }
  return out;
}

/** Tính hướng Trái/Phải so le tự nhiên cho các bong bóng nổi không khung trên 3D */
function computeFloatingSides(items: OfficeChatMessage[]): ('left' | 'right')[] {
  const sides: ('left' | 'right')[] = [];
  for (let i = 0; i < items.length; i += 1) {
    const cur = items[i];
    const prev = i > 0 ? items[i - 1] : null;
    if (prev && prev.from === cur.from) {
      sides.push(sides[i - 1]);
      continue;
    }
    const preferred: 'left' | 'right' = isRightSideAgent(cur.from) ? 'right' : 'left';
    if (prev && sides[i - 1] === preferred) {
      // Hai Agent khác nhau nói liền nhau -> tự động so le Trái/Phải cho thoáng mắt trên 3D
      sides.push(preferred === 'left' ? 'right' : 'left');
    } else {
      sides.push(preferred);
    }
  }
  return sides;
}

/**
 * V11 Frameless Floating Chat Overlay (Không đóng khung trên 3D):
 * - Các bong bóng tin nhắn trôi nổi tự nhiên trực tiếp trên không gian 3D, so le Trái – Phải.
 * - Hiển thị 2–3 tin gần nhất: tin cũ mờ dần và tan lên không trung bằng GSAP khi có tin mới.
 * - Có bong bóng 3 chấm đang trả lời (•••) kèm Avatar & Logo riêng của từng Agent đang xử lý (kể cả khi chạy song song).
 */
export function OfficeLiveBubbles({
  messages,
  activeWorkers = [],
  leadActor = null,
  activeWorkLabel,
  finished,
  onFocusAgent,
  onOpenChat,
}: {
  messages: OfficeChatMessage[];
  activeWorkers?: AgentId[];
  leadActor?: AgentId | null;
  activeWorkLabel: string | null;
  finished: boolean;
  onFocusAgent: (id: AgentId) => void;
  onOpenChat: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const prevTopIdRef = useRef<string | null>(null);
  const prevCountRef = useRef<number>(messages.length);
  const [exitingMsg, setExitingMsg] = useState<OfficeChatMessage | null>(null);

  const visible = useMemo(() => messages.slice(-3), [messages]);
  const sides = useMemo(() => computeFloatingSides(visible), [visible]);
  const workingSet = useMemo(() => new Set<AgentId>(activeWorkers), [activeWorkers]);

  const typingAgents: AgentId[] = useMemo(() => {
    if (finished) return [];
    if (activeWorkers.length > 0) return activeWorkers.slice(0, 4);
    if (leadActor && AGENT_PROFILES[leadActor]) return [leadActor];
    if (activeWorkLabel) return ['orchestrator'];
    return [];
  }, [finished, activeWorkers, leadActor, activeWorkLabel]);

  // Tin thứ 4 vừa bị đẩy lên -> mượt mà fade-out và tan lên không trung
  useEffect(() => {
    const prevCount = prevCountRef.current;
    prevCountRef.current = messages.length;
    if (messages.length > prevCount && messages.length > 3) {
      const pushedOut = messages[messages.length - 4];
      if (pushedOut && pushedOut.id !== prevTopIdRef.current) {
        prevTopIdRef.current = pushedOut.id;
        setExitingMsg(pushedOut);
        const timer = window.setTimeout(() => setExitingMsg(null), 340);
        return () => window.clearTimeout(timer);
      }
    }
    if (messages.length <= 3) setExitingMsg(null);
    return undefined;
  }, [messages]);

  useGSAP(
    () => {
      if (prefersReducedMotion()) return;
      const latestEl = containerRef.current?.querySelector('.o3d-fbubble-row.is-newest');
      if (latestEl) {
        gsap.fromTo(
          latestEl,
          { opacity: 0, y: 14, scale: 0.94 },
          { opacity: 1, y: 0, scale: 1, duration: 0.36, ease: 'back.out(1.2)', overwrite: true, clearProps: 'opacity,transform' },
        );
      }
      const exitEl = containerRef.current?.querySelector('.o3d-fbubble-row.is-exiting');
      if (exitEl) {
        gsap.fromTo(
          exitEl,
          { opacity: 0.4, y: 0, scale: 0.92 },
          { opacity: 0, y: -18, scale: 0.88, duration: 0.3, ease: 'power2.in', overwrite: true },
        );
      }
    },
    { scope: containerRef, dependencies: [messages.length, exitingMsg?.id] },
  );

  if (!visible.length && !typingAgents.length) return null;

  const lastSide = sides[sides.length - 1] ?? 'left';
  const typingSide: 'left' | 'right' =
    typingAgents.length === 1 && isRightSideAgent(typingAgents[0])
      ? 'right'
      : typingAgents.length === 1
        ? (lastSide === 'left' ? 'right' : 'left')
        : 'left';

  const typingNames = typingAgents.map((id) => SHORT_LABEL_VI[id]).join(', ');

  return (
    <section
      ref={containerRef}
      className="o3d-fchat"
      aria-label="Hội thoại trực tiếp giữa các Agent"
    >
      <div className="o3d-fchat-stream">
        {exitingMsg && (
          <div className={`o3d-fbubble-row is-exiting ${isRightSideAgent(exitingMsg.from) ? 'is-right' : 'is-left'}`} aria-hidden="true">
            <AgentRobotAvatar agentId={exitingMsg.from} size={24} mood={exitingMsg.mood} showCrest={false} />
            <div className="o3d-fbubble-pill is-glass">
              <p className="o3d-fbubble-text">{exitingMsg.text}</p>
            </div>
          </div>
        )}

        {visible.map((msg, idx) => {
          const fromEnd = visible.length - 1 - idx;
          const depthClass = fromEnd === 0 ? 'is-newest' : fromEnd === 1 ? 'is-mid' : 'is-oldest';
          const side = sides[idx];
          const sender = AGENT_PROFILES[msg.from];
          const accent = sender?.accentHex ?? '#4f46e5';
          const isLeadStyle = isRightSideAgent(msg.from);
          const isWorkingNow = !finished && workingSet.has(msg.from);
          const showTo = msg.to !== 'all';

          return (
            <div
              key={msg.id}
              className={`o3d-fbubble-row is-${side} ${depthClass}`}
              style={{ '--o3d-accent': accent } as CSSProperties}
            >
              {side === 'left' && (
                <button
                  type="button"
                  className="o3d-fbubble-ava"
                  onClick={() => onFocusAgent(msg.from)}
                  title={`Xem bàn ${sender?.name ?? msg.from}`}
                >
                  <AgentRobotAvatar
                    agentId={msg.from}
                    size={fromEnd === 0 ? 32 : 26}
                    mood={msg.mood}
                    online={isWorkingNow}
                    showCrest={fromEnd < 2}
                  />
                </button>
              )}

              <button
                type="button"
                className="o3d-fbubble-wrap"
                onClick={() => onFocusAgent(msg.from)}
                title={`Xem bàn ${sender?.name ?? msg.from}`}
              >
                <div className="o3d-fbubble-meta">
                  <span className="o3d-fbubble-who" style={{ color: accent }}>
                    <AgentRoleLogo agentId={msg.from} size={11} color={accent} />
                    <b>{sender?.shortName ?? msg.from}</b>
                  </span>
                  {showTo && (
                    <span className="o3d-fbubble-to">
                      @{recipientLabel(msg.to)}
                    </span>
                  )}
                  {msg.badge && fromEnd === 0 && (
                    <span
                      className={`o3d-fbubble-status${
                        msg.badge === 'Một phần'
                          ? ' is-partial'
                          : msg.badge === 'Không đủ bằng chứng'
                            ? ' is-nodata'
                            : ' is-complete'
                      }`}
                    >
                      {msg.badge}
                    </span>
                  )}
                </div>

                <div
                  className={`o3d-fbubble-pill ${
                    isLeadStyle
                      ? msg.from === 'integrator'
                        ? 'is-integrator'
                        : 'is-orch'
                      : 'is-glass'
                  }`}
                >
                  <p className="o3d-fbubble-text">{msg.text}</p>
                </div>
              </button>

              {side === 'right' && (
                <button
                  type="button"
                  className="o3d-fbubble-ava"
                  onClick={() => onFocusAgent(msg.from)}
                  title={`Xem bàn ${sender?.name ?? msg.from}`}
                >
                  <AgentRobotAvatar
                    agentId={msg.from}
                    size={fromEnd === 0 ? 32 : 26}
                    mood={msg.mood}
                    online={isWorkingNow}
                    showCrest={fromEnd < 2}
                  />
                </button>
              )}
            </div>
          );
        })}

        {/* Bong bóng 3 dấu chấm đang trả lời kèm cụm Logo của từng Agent đang làm việc */}
        {typingAgents.length > 0 && (
          <div className={`o3d-fbubble-row is-${typingSide} is-typing`} role="status">
            {typingSide === 'left' && (
              <div className="o3d-typing-stack">
                {typingAgents.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className="o3d-typing-ava"
                    onClick={() => onFocusAgent(id)}
                    title={`${AGENT_PROFILES[id]?.name ?? id} đang xử lý`}
                  >
                    <AgentRobotAvatar agentId={id} size={28} mood="focus" online showCrest />
                  </button>
                ))}
              </div>
            )}

            <div className="o3d-ftyping-bubble" aria-label={`${typingNames} đang trả lời`}>
              <span className="o3d-typing-dots" aria-hidden="true">
                <i /><i /><i />
              </span>
              <span className="o3d-ftyping-label">
                {typingAgents.length > 1
                  ? `${typingNames} đang phản hồi…`
                  : `${typingNames} đang trả lời…`}
              </span>
            </div>

            {typingSide === 'right' && (
              <div className="o3d-typing-stack">
                {typingAgents.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className="o3d-typing-ava"
                    onClick={() => onFocusAgent(id)}
                    title={`${AGENT_PROFILES[id]?.name ?? id} đang xử lý`}
                  >
                    <AgentRobotAvatar agentId={id} size={28} mood="focus" online showCrest />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Nút viên kính siêu gọn mở toàn bộ cuộc trò chuyện (không tạo khung nặng) */}
      <div className="o3d-fchat-bar">
        <button
          type="button"
          className="o3d-fchat-pill"
          onClick={onOpenChat}
          title="Mở toàn bộ lịch sử trò chuyện giữa các Agent"
        >
          <span className={`o3d-fchat-pill-dot${finished ? ' is-done' : ''}`} aria-hidden="true" />
          <MessageSquareText size={12.5} />
          <span>Hội thoại ({messages.length})</span>
          <ArrowUpRight size={12.5} />
        </button>
      </div>
    </section>
  );
}

/** Giữ alias xuất khẩu tương thích với các file khác. */
export const OfficeLiveStack = OfficeLiveBubbles;
export const OfficeLiveTicker = OfficeLiveBubbles;

/**
 * V11 OfficeChatFeed — Giao diện nhắn tin tự nhiên, sạch, mềm mại (không viền dọc AI, có Avatar cả 2 phía & 3 dấu chấm sống động).
 */
export function OfficeChatFeed({
  question,
  mode,
  variant,
  messages,
  activeAgents,
  activeWorkers = [],
  leadActor,
  activeWorkLabel,
  waitingSec,
  finished,
  failed,
  onFocusAgent,
  onClose,
  title = 'Nhóm điều phối C27',
}: OfficeChatFeedProps) {
  const rootRef = useRef<HTMLElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);
  const [showJumpDown, setShowJumpDown] = useState(false);
  const [filterAgent, setFilterAgent] = useState<AgentId | null>(null);
  const [briefExpanded, setBriefExpanded] = useState(false);

  useEffect(() => {
    setFilterAgent(null);
    setBriefExpanded(false);
  }, [question]);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    pinnedRef.current = dist < 56;
    setShowJumpDown(dist > 140);
  };

  const scrollToBottom = () => {
    const el = listRef.current;
    if (!el) return;
    pinnedRef.current = true;
    setShowJumpDown(false);
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  };

  const visibleMessages = useMemo(() => {
    if (!filterAgent) return messages;
    return messages.filter((m) => m.from === filterAgent || m.to === filterAgent);
  }, [messages, filterAgent]);

  useEffect(() => {
    const el = listRef.current;
    if (!el || !pinnedRef.current) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [visibleMessages.length, activeWorkLabel, finished]);

  // GSAP: tin nhắn mới nảy mềm tự nhiên như app nhắn tin di động
  useGSAP(
    () => {
      if (prefersReducedMotion() || !visibleMessages.length) return;
      const latest = rootRef.current?.querySelector('[data-msg-latest="true"]');
      if (latest) {
        gsap.fromTo(
          latest,
          { opacity: 0, y: 10, scale: 0.96 },
          { opacity: 1, y: 0, scale: 1, duration: 0.3, ease: 'power3.out', overwrite: true, clearProps: 'opacity,transform' },
        );
      }
    },
    { scope: rootRef, dependencies: [visibleMessages.length] },
  );

  const members = useMemo(() => {
    const seen = new Set<AgentId>();
    const list: AgentId[] = [];
    for (const m of messages) {
      if (!seen.has(m.from)) {
        seen.add(m.from);
        list.push(m.from);
      }
    }
    for (const id of activeAgents) {
      if (!seen.has(id)) {
        seen.add(id);
        list.push(id);
      }
    }
    return list;
  }, [messages, activeAgents]);

  // Đồng bộ 1:1 với luồng nối 3D — chỉ Agent đang trong activeWorkers mới sáng nhịp hoạt động
  const workingSet = useMemo(
    () => new Set<AgentId>(finished ? [] : activeWorkers),
    [finished, activeWorkers],
  );

  const typingAgents: AgentId[] = useMemo(() => {
    if (finished || filterAgent) return [];
    if (activeWorkers.length > 0) return activeWorkers.slice(0, 4);
    if (leadActor && AGENT_PROFILES[leadActor]) return [leadActor];
    if (activeWorkLabel) return ['orchestrator'];
    return [];
  }, [finished, filterAgent, activeWorkers, leadActor, activeWorkLabel]);

  const handleStoryClick = (id: AgentId) => {
    onFocusAgent(id);
    setFilterAgent((cur) => (cur === id ? null : id));
  };

  const statusText = finished
    ? failed
      ? 'Phiên bị gián đoạn'
      : 'Đã hoàn tất'
    : activeWorkers.length > 1
      ? `${activeWorkers.length} Agent đang trả lời song song`
      : mode === 'demo'
        ? 'Đang minh họa'
        : 'Đang trò chuyện';

  const typingNames = typingAgents.map((id) => SHORT_LABEL_VI[id]).join(', ');

  return (
    <aside
      ref={rootRef}
      className={`o3d-chat-shell ${variant === 'full-tab' ? 'is-full-tab' : 'is-floating-side'}`}
      aria-label="Nhóm trò chuyện nội bộ của đội Agent"
    >
      {/* 1. Header trắng sạch mềm mại kiểu ứng dụng nhắn tin hiện đại */}
      <header className="o3d-chat-head">
        <div className="o3d-chat-head-left">
          <div className="o3d-chat-group-stack" aria-hidden="true">
            <AgentRobotAvatar agentId="orchestrator" size={34} mood="happy" showCrest />
          </div>
          <div className="o3d-chat-head-meta">
            <h2>{title}</h2>
            <span className={`o3d-chat-presence ${finished ? (failed ? 'is-fail' : 'is-done') : 'is-online'}`}>
              <i aria-hidden="true" />
              {statusText}
              {members.length > 0 ? ` · ${members.length} thành viên` : ''}
            </span>
          </div>
        </div>

        <div className="o3d-chat-head-right">
          {variant === 'floating-side' && onClose && (
            <button
              type="button"
              className="o3d-chat-close"
              onClick={onClose}
              title="Thu gọn khung trò chuyện"
              aria-label="Thu gọn khung trò chuyện"
            >
              <ChevronRight size={16} />
            </button>
          )}
        </div>
      </header>

      {/* 2. Dải thành viên tròn mượt (Stories) — không kẻ đường chia thô */}
      {members.length > 0 && (
        <div className="o3d-chat-stories" aria-label="Thành viên tham gia — bấm để xem bàn và lọc tin nhắn">
          {members.map((id) => {
            const p = AGENT_PROFILES[id];
            const accent = p?.accentHex ?? '#4f46e5';
            const isWorking = workingSet.has(id);
            const isFiltered = filterAgent === id;
            return (
              <button
                key={id}
                type="button"
                className={`o3d-chat-story${isWorking ? ' is-working' : ' is-resting'}${isFiltered ? ' is-selected' : ''}`}
                style={{ '--o3d-accent': accent } as CSSProperties}
                onClick={() => handleStoryClick(id)}
                title={
                  isFiltered
                    ? `Đang lọc tin của ${p?.shortName ?? id}. Bấm lại để hiện tất cả`
                    : `${p?.name ?? id} (${isWorking ? 'đang xử lý' : 'đã xong / chờ'}) — bấm để xem bàn & lọc tin`
                }
              >
                <span className="o3d-chat-story-ring">
                  <AgentRobotAvatar
                    agentId={id}
                    size={34}
                    mood={finished && id === 'integrator' ? 'happy' : 'focus'}
                    online={isWorking}
                  />
                </span>
                <span className="o3d-chat-story-name">{SHORT_LABEL_VI[id]}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* 3. Dải Yêu cầu ghim thanh thoát kiểu Telegram (không vạch dọc thô) */}
      {question && (
        <div className="o3d-chat-pin-wrap">
          <div className={`o3d-chat-pin${briefExpanded ? ' is-expanded' : ''}`}>
            <button
              type="button"
              className="o3d-chat-pin-btn"
              onClick={() => setBriefExpanded((v) => !v)}
              title={briefExpanded ? 'Thu gọn câu hỏi' : 'Bấm để đọc trọn câu hỏi'}
            >
              <Pin size={12} className="o3d-chat-pin-ico" aria-hidden="true" />
              <p className="o3d-chat-pin-text">{question}</p>
            </button>
            {filterAgent && (
              <button
                type="button"
                className="o3d-chat-clear-filter"
                onClick={() => setFilterAgent(null)}
                title="Bỏ lọc, hiện toàn bộ cuộc trò chuyện"
              >
                <FilterX size={11} />
                <span>Tất cả</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* 4. Luồng bong bóng trò chuyện 2 phía tự nhiên (có Avatar ở cả Trái & Phải, bỏ sạch border-left AI) */}
      <div className="o3d-chat-stream-wrap">
        <div className="o3d-chat-stream" ref={listRef} onScroll={handleScroll} role="log" aria-live="polite">
          {visibleMessages.length === 0 ? (
            <div className="o3d-chat-empty">
              <AgentRobotAvatar agentId={filterAgent ?? 'orchestrator'} size={50} mood="happy" />
              <p>{filterAgent ? `Chưa có trao đổi của ${SHORT_LABEL_VI[filterAgent]}` : 'Sẵn sàng trò chuyện'}</p>
              <small>
                {filterAgent
                  ? 'Bấm “Tất cả” phía trên để xem đầy đủ cuộc hội thoại của cả nhóm.'
                  : 'Gửi câu hỏi để theo dõi từng Agent trao đổi trực tiếp với nhau tại đây.'}
              </small>
            </div>
          ) : (
            visibleMessages.map((msg, idx) => {
              const prev = idx > 0 ? visibleMessages[idx - 1] : null;
              const next = idx < visibleMessages.length - 1 ? visibleMessages[idx + 1] : null;
              const showPhase = !prev || prev.phase !== msg.phase;
              const samePrev = Boolean(prev && !showPhase && prev.from === msg.from);
              const sameNext = Boolean(next && next.phase === msg.phase && next.from === msg.from);
              const isLatest = idx === visibleMessages.length - 1;

              const isRight = isRightSideAgent(msg.from);
              const isIntegratorDone = msg.from === 'integrator' && (msg.to === 'user' || msg.kind === 'done');
              const isOrchestrator = msg.from === 'orchestrator';
              const sender = AGENT_PROFILES[msg.from];
              const accent = sender?.accentHex ?? '#4f46e5';
              const canFocusTo = msg.to !== 'all' && msg.to !== 'user';
              const showMention = msg.to !== 'all';

              const posClass = samePrev && sameNext
                ? 'is-mid'
                : samePrev
                  ? 'is-last'
                  : sameNext
                    ? 'is-first'
                    : 'is-single';

              const showFileCard = Boolean(
                msg.attachment && (msg.attachment.icon === 'doc' || msg.attachment.icon === 'qc_ok' || msg.attachment.icon === 'qc_warn'),
              );

              const bubbleTone = isRight
                ? isOrchestrator
                  ? 'is-orch'
                  : 'is-integrator'
                : 'is-specialist';

              const deliverStatusTone =
                msg.badge === 'Một phần'
                  ? 'is-partial'
                  : msg.badge === 'Không đủ bằng chứng'
                    ? 'is-nodata'
                    : 'is-complete';

              return (
                <div key={msg.id} className="o3d-chat-block" data-msg-latest={isLatest ? 'true' : undefined}>
                  {showPhase && (
                    <div className="o3d-chat-phase" role="separator">
                      <span>{PHASE_LABEL_VI[msg.phase]}</span>
                    </div>
                  )}

                  <div
                    className={`o3d-chat-row ${isRight ? 'is-right' : 'is-left'} ${posClass}`}
                    style={{ '--o3d-accent': accent } as CSSProperties}
                  >
                    {!isRight && (
                      <div className="o3d-chat-ava-slot">
                        {!sameNext && (
                          <button
                            type="button"
                            className="o3d-chat-ava-btn"
                            onClick={() => onFocusAgent(msg.from)}
                            title={`Xem bàn ${sender?.name ?? msg.from}`}
                          >
                            <AgentRobotAvatar
                              agentId={msg.from}
                              size={30}
                              mood={msg.mood}
                              online={workingSet.has(msg.from)}
                            />
                          </button>
                        )}
                      </div>
                    )}

                    <div className="o3d-chat-col">
                      {!samePrev && (
                        <button
                          type="button"
                          className="o3d-chat-author"
                          onClick={() => onFocusAgent(msg.from)}
                          title={`Xem bàn ${sender?.name ?? msg.from}`}
                        >
                          <AgentRoleLogo agentId={msg.from} size={11} color={accent} />
                          <span style={{ color: accent }}>{sender?.shortName ?? msg.from}</span>
                        </button>
                      )}

                      <div
                        className={`o3d-chat-bubble ${bubbleTone}${msg.kind === 'error' ? ' is-error' : ''}${msg.kind === 'revise' ? ' is-warn' : ''}`}
                      >
                        {showMention && (
                          canFocusTo ? (
                            <button
                              type="button"
                              className="o3d-chat-mention is-clickable"
                              style={{ '--o3d-mention-c': recipientAccent(msg.to) } as CSSProperties}
                              onClick={() => onFocusAgent(msg.to as AgentId)}
                              title={`Xem bàn ${recipientLabel(msg.to)}`}
                            >
                              @{recipientLabel(msg.to)}
                            </button>
                          ) : (
                            <span
                              className="o3d-chat-mention"
                              style={{ '--o3d-mention-c': recipientAccent(msg.to) } as CSSProperties}
                            >
                              @{recipientLabel(msg.to)}
                            </span>
                          )
                        )}
                        {showMention ? ' ' : ''}
                        {msg.text}
                      </div>

                      {showFileCard && msg.attachment && (
                        <div className={`o3d-chat-media is-${msg.attachment.icon}`}>
                          <span className="o3d-chat-media-ico" aria-hidden="true">
                            <AttachmentGlyph icon={msg.attachment.icon} />
                          </span>
                          <div className="o3d-chat-media-info">
                            <b title={msg.attachment.title}>{msg.attachment.title}</b>
                            {msg.attachment.subtitle && <span>{msg.attachment.subtitle}</span>}
                          </div>
                        </div>
                      )}

                      {isIntegratorDone && !sameNext && (
                        <span className={`o3d-chat-seen ${deliverStatusTone}`}>
                          <CheckCheck size={13} />
                          <span>{msg.badge ? `Đã gửi · ${msg.badge}` : 'Đã gửi tới người dùng'}</span>
                        </span>
                      )}
                    </div>

                    {isRight && (
                      <div className="o3d-chat-ava-slot">
                        {!sameNext && (
                          <button
                            type="button"
                            className="o3d-chat-ava-btn"
                            onClick={() => onFocusAgent(msg.from)}
                            title={`Xem bàn ${sender?.name ?? msg.from}`}
                          >
                            <AgentRobotAvatar
                              agentId={msg.from}
                              size={30}
                              mood={msg.mood}
                              online={workingSet.has(msg.from)}
                            />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}

          {/* Bong bóng 3 dấu chấm đang trả lời kèm cụm Avatar + Logo từng Agent đang xử lý */}
          {typingAgents.length > 0 && (
            <div className="o3d-chat-row is-left is-single o3d-chat-typing-row" role="status">
              <div className="o3d-typing-stack">
                {typingAgents.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className="o3d-typing-ava"
                    onClick={() => onFocusAgent(id)}
                    title={`${AGENT_PROFILES[id]?.name ?? id} đang phản hồi`}
                  >
                    <AgentRobotAvatar agentId={id} size={28} mood="focus" online showCrest />
                  </button>
                ))}
              </div>
              <div className="o3d-chat-col">
                <div className="o3d-chat-typing-bubble" aria-label={activeWorkLabel || `${typingNames} đang trả lời`}>
                  <span className="o3d-typing-dots" aria-hidden="true">
                    <i /><i /><i />
                  </span>
                </div>
                <span className="o3d-chat-typing-caption">
                  {activeWorkLabel || `${typingNames} đang trả lời…`}
                  {waitingSec !== null && waitingSec > 0 ? ` (${waitingSec}s)` : ''}
                </span>
              </div>
            </div>
          )}
        </div>

        {showJumpDown && (
          <button
            type="button"
            className="o3d-chat-jumpdown"
            onClick={scrollToBottom}
            title="Xuống tin nhắn mới nhất"
            aria-label="Xuống tin nhắn mới nhất"
          >
            <ArrowDown size={15} />
          </button>
        )}
      </div>

      {/* 5. Chân khung chat dạng thanh viên thuốc mềm mại tự nhiên */}
      <footer className="o3d-chat-foot">
        <div className="o3d-chat-pill-bar">
          {typingAgents.length > 0 ? (
            <span className="o3d-chat-foot-logos" aria-hidden="true">
              {typingAgents.slice(0, 3).map((id) => (
                <span key={id} className="o3d-chat-foot-logo" style={{ color: AGENT_PROFILES[id]?.accentHex }}>
                  <AgentRoleLogo agentId={id} size={11} color={AGENT_PROFILES[id]?.accentHex ?? '#4f46e5'} />
                </span>
              ))}
            </span>
          ) : (
            <span className={`o3d-chat-foot-dot${finished ? ' is-done' : ''}`} aria-hidden="true" />
          )}
          <span className="o3d-chat-foot-text">
            {filterAgent
              ? `Đang xem ${visibleMessages.length} tin của ${SHORT_LABEL_VI[filterAgent]}`
              : finished
                ? `Phiên làm việc đã hoàn tất · ${messages.length} tin nhắn`
                : typingAgents.length > 1
                  ? `${typingNames} đang phối hợp song song…`
                  : `${typingNames || 'Đội Agent'} đang trao đổi…`}
          </span>
        </div>
      </footer>
    </aside>
  );
}
