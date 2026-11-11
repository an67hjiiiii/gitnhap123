import { useState } from "react";
import { CopyIcon, FileTextIcon, SpinnerGapIcon, WarningCircleIcon } from "@phosphor-icons/react";
import type { ConversationDetail, ConversationMessage, RunMetrics, RunRecord, RunStatus } from "../types/api";
import { ChatComposer } from "./ChatComposer";
import { getStatusTone, normalizeStatus, StatusBadge } from "./StatusBadge";
import { displayConversationTitle, messagesForConversation, productAnswerText } from "../app/chatModel.mjs";
import type { SourceImportResult } from "../types/api";
import "./product/product-conversation.css";

interface ChatPanelProps {
  researchMode: boolean;
  showImport?: boolean;
  run: RunRecord | null;
  conversation: ConversationDetail | null;
  conversationRuns: Record<string, RunRecord>;
  activeConversationId?: string | null;
  onSelectRun: (runId: string) => void;
  pendingQuestion?: string | null;
  condition?: string;
  provider?: string;
  isRunning: boolean;
  isImporting: boolean;
  sourceNotice: string | null;
  onSubmit: (message: string) => Promise<void>;
  onImport: (file: File) => Promise<void | SourceImportResult | null>;
  onOpenSources?: (run: RunRecord, trigger: HTMLButtonElement) => void;
}

const statusDescriptions: Record<string, string> = {
  READY: "Ready for a new question",
  RUNNING: "Retrieving evidence and generating an answer",
  COMPLETE: "Answer ready",
  PARTIAL: "Answer needs review",
  NO_EVIDENCE: "No validated evidence found",
  FAILED: "Run failed",
};

export function getChatStatus(run: RunRecord | null, isRunning: boolean): RunStatus {
  return isRunning ? "RUNNING" : run?.status ?? "READY";
}

export function formatMetricValue(
  value: number | string | null | undefined,
  suffix = "",
): string {
  if (value === null || value === undefined || value === "") return "—";
  const formatted = typeof value === "number" ? new Intl.NumberFormat().format(value) : value;
  return `${formatted}${suffix}`;
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function ProductAnswerStatus({ status }: { status?: RunStatus }) {
  const normalized = normalizeStatus(status);
  const role = normalized === "FAILED" ? "alert" : "status";
  if (normalized === "RUNNING") return <span className="product-answer-status" role={role}><SpinnerGapIcon className="product-status-spinner" size={16} aria-hidden="true" /> Đang xử lý</span>;
  if (normalized === "PARTIAL") return <span className="product-answer-status product-status-warning" role={role}><WarningCircleIcon size={16} aria-hidden="true" /> Câu trả lời một phần</span>;
  if (normalized === "NO_EVIDENCE") return <span className="product-answer-status product-status-warning" role={role}><WarningCircleIcon size={16} aria-hidden="true" /> Chưa có nguồn phù hợp</span>;
  if (normalized === "FAILED") return <span className="product-answer-status product-status-failed" role={role}><WarningCircleIcon size={16} aria-hidden="true" /> Chưa thể hoàn thành</span>;
  return null;
}

function statusDescription(status: RunStatus): string {
  return statusDescriptions[normalizeStatus(status)] ?? "Run status received";
}

function RunStatusCard({
  run,
  status,
  condition,
  provider,
}: {
  run: RunRecord | null;
  status: RunStatus;
  condition: string;
  provider: string;
}) {
  const normalizedStatus = normalizeStatus(status);
  const runId = run?.run_id;

  return (
    <section className={`run-status-card run-status-${getStatusTone(normalizedStatus)}`} aria-label="Current run status">
      <div className="run-status-summary">
        <span className="run-status-kicker">Run status</span>
        <div className="run-status-value">
          <StatusBadge status={normalizedStatus} />
          <span>{statusDescription(normalizedStatus)}</span>
        </div>
      </div>
      <dl className="run-status-meta">
        <div><dt>Condition</dt><dd>{run?.condition ?? condition}</dd></div>
        <div><dt>Profile</dt><dd>{run?.implementation_profile ?? "vanilla-rag"}</dd></div>
        <div><dt>Provider</dt><dd>{run?.provider ?? provider}</dd></div>
        <div><dt>Run</dt><dd title={runId}>{runId ? runId.slice(-8) : "pending"}</dd></div>
      </dl>
    </section>
  );
}

function RuntimeMetrics({ metrics }: { metrics?: RunMetrics }) {
  const totalTokens = metrics?.total_tokens ?? (
    typeof metrics?.input_tokens === "number" && typeof metrics.output_tokens === "number"
      ? metrics.input_tokens + metrics.output_tokens
      : undefined
  );
  const entries = [
    ["Latency", formatMetricValue(metrics?.latency_ms, " ms")],
    ["LLM calls", formatMetricValue(metrics?.llm_calls)],
    ["Tokens", formatMetricValue(totalTokens)],
    ["Selected chunks", formatMetricValue(metrics?.selected_chunks)],
    ["Valid citations", formatMetricValue(metrics?.citations_valid)],
  ] as const;
  const hasValues = entries.some(([, value]) => value !== "—");

  return (
    <section className="run-metrics" aria-label="Basic runtime metrics">
      <div className="run-metrics-heading"><span>Runtime metrics</span><span>Quality not evaluated</span></div>
      {hasValues ? (
        <div className="run-metrics-grid">
          {entries.map(([label, value]) => <div className="run-metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}
        </div>
      ) : <p className="run-metrics-empty">This run did not return runtime measurements.</p>}
    </section>
  );
}

function AnswerBlock({ run, citations }: { run: RunRecord; citations: string[] }) {
  const missingInformation = unique((run.task_results ?? []).flatMap((result) => result.missing_information ?? []));
  const invalidCitations = unique((run.task_results ?? []).flatMap((result) => result.invalid_citations ?? []));
  const answer = run.answer?.trim();

  return (
    <section className={`answer-block answer-${getStatusTone(run.status)}`} aria-label="Research answer">
      <div className="answer-heading">
        <div className="answer-heading-identity">
          <span className="answer-avatar" aria-hidden="true">LR</span>
          <div><span className="message-label">Research answer</span><span className="answer-meta">Condition {run.condition ?? "A"} · source-grounded</span></div>
        </div>
        <StatusBadge status={run.status} />
      </div>
      {answer ? <p className="answer-copy">{answer}</p> : run.error ? <p className="answer-error" role="alert">{run.error}</p> : <p className="answer-copy answer-copy-muted">No answer was returned for this run.</p>}
      {missingInformation.length > 0 && <div className="answer-note"><strong>Missing information</strong><span>{missingInformation.join(" · ")}</span></div>}
      {citations.length > 0 && <div className="answer-citations"><span className="citation-label">Validated citations</span>{citations.map((citation) => <span className="citation-chip" key={citation}>{citation}</span>)}</div>}
      {invalidCitations.length > 0 && <p className="citation-warning">{invalidCitations.length} citation{invalidCitations.length === 1 ? "" : "s"} were excluded because their locators could not be validated.</p>}
      <RuntimeMetrics metrics={run.metrics} />
    </section>
  );
}

function PendingAnswer({ researchMode = true }: { researchMode?: boolean }) {
  if (!researchMode) {
    return (
      <section className="product-message product-message-assistant product-pending-answer" aria-label="Đang xử lý câu hỏi">
        <ProductAnswerStatus status="RUNNING" />
        <p>Đang tìm tài liệu phù hợp và chuẩn bị câu trả lời.</p>
      </section>
    );
  }
  return (
    <section className="answer-block answer-pending" aria-label="Answer in progress">
      <div className="answer-heading">
        <div className="answer-heading-identity"><span className="answer-avatar" aria-hidden="true">LR</span><div><span className="message-label">Research answer</span><span className="answer-meta">Waiting for the bounded local run</span></div></div>
        <StatusBadge status="RUNNING" />
      </div>
      <p className="answer-copy answer-copy-muted">Retrieving local evidence and validating citations…</p>
    </section>
  );
}

function ProductConversation({
  conversation,
  conversationRuns,
  activeConversationId,
  pendingQuestion,
  isRunning,
  onSelectRun,
  onOpenSources,
}: {
  conversation: ConversationDetail | null;
  conversationRuns: Record<string, RunRecord>;
  activeConversationId: string | null;
  pendingQuestion: string | null;
  isRunning: boolean;
  onSelectRun: (runId: string) => void;
  onOpenSources?: (run: RunRecord, trigger: HTMLButtonElement) => void;
}) {
  if (activeConversationId && !conversation) {
    return <div className="product-conversation-loading" role="status">Đang mở cuộc trò chuyện…</div>;
  }
  const messages = messagesForConversation(conversation, activeConversationId);
  if (messages.length === 0 && !pendingQuestion && !isRunning) return null;
  return (
    <article className="product-conversation-thread">
      {messages.map((message: ConversationMessage) => {
        if (message.role === "USER") {
          return (
            <div className="product-message product-message-user" key={message.message_id}>
              <p>{message.content}</p>
            </div>
          );
        }
        const run = message.run_id ? conversationRuns[message.run_id] : undefined;
        const citations = Array.from(new Set((run?.task_results ?? []).flatMap((result) => result.citations ?? [])));
        const missingInformation = unique((run?.task_results ?? []).flatMap((result) => result.missing_information ?? []));
        const answerStatus = normalizeStatus(run?.status);
        const answerSource = message.content.trim() || run?.answer?.trim() || "";
        const answerText = answerStatus === "NO_EVIDENCE"
          ? "Chưa tìm thấy tài liệu phù hợp để trả lời câu hỏi này. Hãy thêm tài liệu liên quan hoặc thử một câu hỏi khác."
          : answerStatus === "FAILED"
            ? "Không thể hoàn thành yêu cầu này. Hãy thử lại."
            : productAnswerText(answerSource, run ?? null);
        const hasAnswerText = answerStatus !== "FAILED" && (Boolean(message.content.trim() || run?.answer?.trim()) || answerStatus === "NO_EVIDENCE");
        return (
          <section className={`product-message product-message-assistant answer-${getStatusTone(run?.status ?? "COMPLETE")}`} key={message.message_id}>
            {run && <ProductAnswerStatus status={run.status} />}
            <div className="product-answer-copy">{answerText}</div>
            {missingInformation.length > 0 && <p className="product-answer-notice"><strong>Thông tin còn thiếu:</strong> {missingInformation.join(" · ")}</p>}
            {answerStatus === "PARTIAL" && missingInformation.length === 0 && <p className="product-answer-notice">Một phần câu trả lời cần được kiểm tra thêm trong các nguồn.</p>}
            {(citations.length > 0 || hasAnswerText) && (
              <div className="product-answer-actions" role="group" aria-label="Thao tác câu trả lời">
                {citations.length > 0 && run && (
                  <button className="product-answer-action" type="button" onClick={(event) => onOpenSources ? onOpenSources(run, event.currentTarget) : onSelectRun(run.run_id)} aria-label="Xem nguồn tham khảo" title="Xem nguồn tham khảo">
                    <FileTextIcon size={19} aria-hidden="true" />
                  </button>
                )}
                {hasAnswerText && <CopyAnswerButton answer={answerText} />}
              </div>
            )}
          </section>
        );
      })}
      {pendingQuestion && (
        <>
          <div className="product-message product-message-user product-pending-message"><p>{pendingQuestion}</p></div>
          {isRunning && <PendingAnswer researchMode={false} />}
        </>
      )}
    </article>
  );
}

function CopyAnswerButton({ answer }: { answer: string }) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [copying, setCopying] = useState(false);

  async function copyAnswer() {
    setCopying(true);
    setCopyFailed(false);
    try {
      await navigator.clipboard.writeText(answer);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
      setCopyFailed(true);
    } finally {
      setCopying(false);
    }
  }

  return (
    <>
      <button className="product-answer-action" type="button" onClick={() => void copyAnswer()} disabled={copying} aria-label={copying ? "Đang sao chép câu trả lời" : "Sao chép câu trả lời"} title={copying ? "Đang sao chép câu trả lời" : "Sao chép câu trả lời"}>
        {copying ? <SpinnerGapIcon className="product-status-spinner" size={19} aria-hidden="true" /> : <CopyIcon size={19} aria-hidden="true" />}
      </button>
      {(copied || copyFailed) && <span className="sr-only" role="status">{copied ? "Đã sao chép câu trả lời" : "Không thể sao chép lúc này."}</span>}
    </>
  );
}

export function ChatPanel({
  researchMode,
  showImport = true,
  run,
  conversation,
  conversationRuns,
  onSelectRun,
  activeConversationId = null,
  pendingQuestion = null,
  condition = "A",
  provider = "local",
  isRunning,
  isImporting,
  sourceNotice,
  onSubmit,
  onImport,
  onOpenSources,
}: ChatPanelProps) {
  const status = getChatStatus(run, isRunning);
  const citations = unique((run?.task_results ?? []).flatMap((result) => result.citations ?? []));

  return (
    <main className={`chat-panel${researchMode ? "" : " product-chat-panel"}`}>
      {(researchMode || activeConversationId || conversation?.conversation_id) && (
        <div className="chat-header">
          <div>
            {researchMode && <p className="eyebrow">M0 research console</p>}
            <h1
              title={researchMode ? undefined : conversation ? displayConversationTitle(conversation) : "Đang mở cuộc trò chuyện…"}
            >
              {researchMode ? "Explore your evidence" : conversation ? displayConversationTitle(conversation) : "Đang mở cuộc trò chuyện…"}
            </h1>
          </div>
          {researchMode && <div className="chat-header-note"><StatusBadge status={status} compact /><span>Runs stay on this machine</span></div>}
        </div>
      )}

      <div className="conversation" aria-live="polite" aria-busy={isRunning}>
        {!researchMode ? (
          <ProductConversation
            conversation={conversation}
            conversationRuns={conversationRuns}
            activeConversationId={activeConversationId}
            pendingQuestion={pendingQuestion}
            isRunning={isRunning}
            onSelectRun={onSelectRun}
            onOpenSources={onOpenSources}
          />
        ) : (
        <>
        {!run && !pendingQuestion && !isRunning ? (
          <div className="welcome-state">
            <div className="welcome-kicker">LOCAL MULTI-AGENT RAG</div>
            <h2>Start with a focused research question.</h2>
            <p>
              Import a text source, then run a question to inspect the answer, evidence trace,
              and runtime metrics together.
            </p>
            <div className="welcome-prompts" aria-label="Example research questions">
              <span>“What risks are documented in this corpus?”</span>
              <span>“Summarize the API architecture evidence.”</span>
            </div>
          </div>
        ) : (
          <article className="conversation-thread">
            <div className="user-message">
              <div className="message-topline">
                <span className="message-label">You</span>
                {isRunning && <span className="message-state">New run in progress</span>}
              </div>
              <p>{pendingQuestion ?? run?.query ?? "Research question"}</p>
            </div>
            <RunStatusCard run={run} status={status} condition={condition} provider={provider} />
            {isRunning || !run ? <PendingAnswer /> : <AnswerBlock run={run} citations={citations} />}
          </article>
        )}

        {isRunning && (
          <div className="running-callout" role="status">
            <span className="loading-bar" aria-hidden="true" />
            <span>Running the local pipeline and assembling evidence…</span>
          </div>
        )}
        </>
        )}
      </div>

      <div className="composer-dock">
        {sourceNotice && <div className="source-notice" role="status">{sourceNotice}</div>}
        <ChatComposer researchMode={researchMode} showImport={showImport} isRunning={isRunning} isImporting={isImporting} onSubmit={onSubmit} onImport={onImport} />
      </div>
    </main>
  );
}
