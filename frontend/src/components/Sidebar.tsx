import type { ConversationSummary, RunListItem, SourceSummary } from "../types/api";
import { StatusBadge } from "./StatusBadge";
import { conversationSidebarItems } from "../app/chatModel.mjs";

interface SidebarProps {
  researchMode: boolean;
  history: RunListItem[];
  conversations: ConversationSummary[];
  sources: SourceSummary[];
  activeRunId?: string;
  activeConversationId?: string | null;
  onNewRun: () => void;
  onSelectRun: (runId: string) => void;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
}
function formatDate(value?: string) {
  if (!value) return "Unknown time";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(
    new Date(value),
  );
}

export function Sidebar({
  researchMode,
  history,
  conversations,
  sources,
  activeRunId,
  activeConversationId,
  onNewRun,
  onSelectRun,
  onNewConversation,
  onSelectConversation,
}: SidebarProps) {
  const productConversations = conversationSidebarItems(conversations);
  return (
    <aside className="sidebar" aria-label={researchMode ? "Research workspace navigation" : "Product workspace navigation"}>
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true">LR</div>
        <div>
          <div className="brand-name">{researchMode ? "Local RAG Lab" : "CAP1_AI"}</div>
          <div className="brand-subtitle">{researchMode ? "Research workspace" : "Local RAG Lab"}</div>
        </div>
      </div>

      <button className="new-run-button" type="button" onClick={researchMode ? onNewRun : onNewConversation}>
        <span aria-hidden="true">＋</span>
        {researchMode ? "New research run" : "New conversation"}
      </button>

      <div className="sidebar-section-heading">
        <span>{researchMode ? "Run history" : "Conversations"}</span>
        <span className="section-count">{researchMode ? history.length : productConversations.length}</span>
      </div>
      <div className="run-history" aria-live="polite">
        {researchMode ? (history.length === 0 ? (
          <p className="sidebar-empty">Your completed runs will appear here.</p>
        ) : (
          history.map((item) => (
            <button
              className={`history-item${item.run_id === activeRunId ? " history-item-active" : ""}`}
              key={item.run_id}
              type="button"
              onClick={() => onSelectRun(item.run_id)}
            >
              <span className="history-item-topline">
                <span className="history-condition">{item.condition ?? "—"}</span>
                <StatusBadge compact status={item.status} />
              </span>
              <span className="history-query">{item.query || "Untitled research run"}</span>
              <span className="history-date">{formatDate(item.created_at)}</span>
            </button>
          ))
        )) : productConversations.length === 0 ? (
          <p className="sidebar-empty">Your conversations will appear here.</p>
        ) : productConversations.map((conversation) => (
          <button
            className={`history-item${conversation.conversation_id === activeConversationId ? " history-item-active" : ""}`}
            key={conversation.conversation_id}
            type="button"
            onClick={() => onSelectConversation(conversation.conversation_id)}
          >
            <span className="history-query">{conversation.label}</span>
            <span className="history-date">{formatDate(conversation.updated_at ?? conversation.created_at)}</span>
          </button>
        ))}
      </div>

      <div className="sidebar-footer">
        <div className="corpus-summary">
          <span className="summary-icon" aria-hidden="true">⌁</span>
          <span>
            <strong>{sources.length} sources</strong>
            <small>Current corpus</small>
          </span>
        </div>
        <div className="local-only-label">
          <span className="status-dot" aria-hidden="true" />
          Local-only build
        </div>
      </div>
    </aside>
  );
}
