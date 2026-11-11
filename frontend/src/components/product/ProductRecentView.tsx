import { displayConversationTitle } from "../../app/chatModel.mjs";
import type { ConversationSummary } from "../../types/api";

interface ProductRecentViewProps {
  conversations: ConversationSummary[];
  isLoading: boolean;
  onOpenConversation: (conversationId: string) => void;
}

export function ProductRecentView({ conversations, isLoading, onOpenConversation }: ProductRecentViewProps) {
  return (
    <main className="product-page product-recent" aria-labelledby="product-recent-title">
      <div className="product-page-heading">
        <div><h1 id="product-recent-title">Gần đây</h1></div>
      </div>
      <section className="product-recent-list" aria-label="Các cuộc trò chuyện gần đây" aria-busy={isLoading}>
        {isLoading ? <p className="product-inline-state" role="status">Đang tải cuộc trò chuyện…</p> : conversations.length === 0 ? (
          <div className="product-empty-panel"><h2>Chưa có cuộc trò chuyện</h2><p>Bắt đầu bằng nút Trò chuyện mới ở thanh bên.</p></div>
        ) : conversations.map((conversation) => (
          <button className="product-recent-list-row" key={conversation.conversation_id} type="button" onClick={() => onOpenConversation(conversation.conversation_id)}>
            <span className="product-recent-list-copy"><strong>{displayConversationTitle(conversation)}</strong><small>{conversation.updated_at ? new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(conversation.updated_at)) : ""}</small></span>
          </button>
        ))}
      </section>
    </main>
  );
}
