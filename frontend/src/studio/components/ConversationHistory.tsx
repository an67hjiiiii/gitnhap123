import React, { useState } from 'react';
import { MessageSquarePlus, Search } from 'lucide-react';
import { Conversation } from '../services/api';
import { serverDate } from '../utils/time';

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
}

function when(s: string) {
  const d = serverDate(s), now = new Date();
  return d.toDateString() === now.toDateString()
    ? d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
}

// Lịch sử thống nhất ở thanh bên: mỗi cuộc trò chuyện chứa cả câu hỏi nhanh lẫn lượt phân tích sâu.
export const ConversationHistory: React.FC<Props> = ({ conversations, activeId, onOpen, onNew }) => {
  const [q, setQ] = useState('');
  const shown = q.trim() ? conversations.filter(c => (c.title || '').toLowerCase().includes(q.trim().toLowerCase())) : conversations;
  return (
    <section className="hist" aria-labelledby="hist-title">
      <div className="hist-head">
        <h2 id="hist-title">Cuộc trò chuyện</h2>
        {conversations.length > 0 && <span className="kb-count">{conversations.length}</span>}
        <button type="button" className="icon-btn is-sm hist-new" onClick={onNew} aria-label="Cuộc trò chuyện mới" title="Cuộc trò chuyện mới"><MessageSquarePlus size={15} /></button>
      </div>
      {conversations.length > 5 && <label className="kb-search"><Search size={14} /><span className="sr">Tìm cuộc trò chuyện</span>
        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm cuộc trò chuyện" /></label>}
      <ul className="hist-list">
        {conversations.length === 0 ? <li className="kb-none">Chưa có cuộc trò chuyện nào.</li>
          : shown.length === 0 ? <li className="kb-none">Không có kết quả.</li>
          : shown.map(c => (
            <li key={c.conversation_id}>
              <button className={`hist-row${activeId === c.conversation_id ? ' is-on' : ''}`} onClick={() => onOpen(c.conversation_id)} aria-current={activeId === c.conversation_id ? 'true' : undefined} title={c.title}>
                <span className="hist-q">{c.title || 'Không tên'}</span>
                <time className="hist-t">{when(c.updated_at)}</time>
              </button>
            </li>
          ))}
      </ul>
    </section>
  );
};
