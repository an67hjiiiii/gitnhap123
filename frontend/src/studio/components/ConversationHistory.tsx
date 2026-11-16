import React, { useEffect, useRef, useState } from 'react';
import { Check, MessageSquarePlus, Pencil, Pin, PinOff, Search, Trash2, X } from 'lucide-react';
import { Conversation, updateConversation } from '../services/api';
import { serverDate } from '../utils/time';

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  /** gọi sau khi đổi tên / ghim / xóa / hoàn tác để tải lại danh sách */
  onChanged?: () => void;
}

// tạo bộ định dạng một lần: toLocale*String tạo mới mỗi lần gọi, chạy cho mọi dòng mỗi lần thanh bên vẽ lại (chuyển trang)
const TIME = new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit' });
const DAY = new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: '2-digit' });
const fold = (v: string) => v.normalize('NFD').replace(/\p{M}/gu, '').replace(/đ/gi, 'd').toLowerCase();
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

function bucket(s: string, today: number): string {
  const days = Math.round((today - startOfDay(serverDate(s))) / 86_400_000);
  return days <= 0 ? 'Hôm nay' : days === 1 ? 'Hôm qua' : days < 7 ? '7 ngày qua' : 'Cũ hơn';
}

// Lịch sử thống nhất ở thanh bên: mỗi cuộc trò chuyện chứa cả câu hỏi nhanh lẫn lượt phân tích sâu.
// Xóa = ẩn khỏi danh sách (backend giữ tin nhắn và lượt chạy cho nghiên cứu), nên hoàn tác được ngay.
export const ConversationHistory: React.FC<Props> = React.memo(function ConversationHistory({ conversations, activeId, onOpen, onNew, onChanged }) {
  const [q, setQ] = useState('');
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const [removed, setRemoved] = useState<Conversation | null>(null);
  const [error, setError] = useState('');
  const undoTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(undoTimer.current), []);

  const run = async (id: string, patch: Parameters<typeof updateConversation>[1]) => {
    setError('');
    try { await updateConversation(id, patch); onChanged?.(); return true; }
    catch (e) { setError(e instanceof Error ? e.message : 'Không thực hiện được.'); return false; }
  };
  const saveTitle = async () => {
    if (!editing) return;
    const title = editing.title.trim();
    const old = conversations.find(c => c.conversation_id === editing.id)?.title;
    if (title && title !== old && !(await run(editing.id, { title }))) return;
    setEditing(null);
  };
  const remove = async (c: Conversation) => {
    if (!(await run(c.conversation_id, { hidden: true }))) return;
    if (c.conversation_id === activeId) onNew();
    setRemoved(c);
    window.clearTimeout(undoTimer.current);
    undoTimer.current = window.setTimeout(() => setRemoved(null), 7000);
  };
  const undo = async () => {
    if (!removed) return;
    window.clearTimeout(undoTimer.current);
    if (await run(removed.conversation_id, { hidden: false })) setRemoved(null);
  };

  const term = fold(q.trim());
  const shown = term ? conversations.filter(c => fold(c.title || '').includes(term)) : conversations;
  // tên trùng nhau thì kèm giờ để phân biệt
  const seen = new Map<string, number>();
  conversations.forEach(c => seen.set(c.title, (seen.get(c.title) ?? 0) + 1));
  const today = startOfDay(new Date());
  const groups: [string, Conversation[]][] = [];
  for (const c of shown) {
    const g = c.pinned ? 'Đã ghim' : bucket(c.updated_at, today);
    const last = groups[groups.length - 1];
    if (last && last[0] === g) last[1].push(c); else groups.push([g, [c]]);
  }
  const label = (c: Conversation) => {
    const d = serverDate(c.updated_at);
    if (startOfDay(d) === today) return TIME.format(d);
    return (seen.get(c.title) ?? 0) > 1 ? `${DAY.format(d)} ${TIME.format(d)}` : DAY.format(d);
  };

  return (
    <section className="hist" aria-labelledby="hist-title">
      <div className="hist-head">
        <h2 id="hist-title">Cuộc trò chuyện</h2>
        {conversations.length > 0 && <span className="kb-count">{conversations.length}</span>}
        <button type="button" className="icon-btn is-sm hist-new" onClick={onNew} aria-label="Cuộc trò chuyện mới" title="Cuộc trò chuyện mới"><MessageSquarePlus size={15} /></button>
      </div>
      {conversations.length > 5 && <label className="kb-search"><Search size={14} /><span className="sr">Tìm cuộc trò chuyện</span>
        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm cuộc trò chuyện" /></label>}
      {removed && <div className="hist-undo" role="status">
        <span>Đã xóa “{removed.title}”</span><button type="button" onClick={undo}>Hoàn tác</button>
      </div>}
      {error && <p className="hist-err" role="alert">{error}</p>}
      <div className="hist-list">
        {conversations.length === 0 ? <p className="kb-none">Chưa có cuộc trò chuyện nào.</p>
          : shown.length === 0 ? <p className="kb-none">Không có kết quả.</p>
          : groups.map(([g, list]) => <section key={g} className="hist-group" aria-label={g}>
            <p className="hist-group-t">{g === 'Đã ghim' && <Pin size={11} />}{g}</p>
            <ul>{list.map(c => {
              const on = activeId === c.conversation_id;
              if (editing?.id === c.conversation_id) return <li key={c.conversation_id}>
                <form className="hist-edit" onSubmit={e => { e.preventDefault(); void saveTitle(); }}>
                  <input autoFocus value={editing.title} maxLength={120} aria-label="Tên cuộc trò chuyện"
                    onChange={e => setEditing({ ...editing, title: e.target.value })}
                    onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); setEditing(null); } }} onFocus={e => e.currentTarget.select()} />
                  <button type="submit" aria-label="Lưu tên" title="Lưu"><Check size={14} /></button>
                  <button type="button" aria-label="Hủy đổi tên" title="Hủy" onClick={() => setEditing(null)}><X size={14} /></button>
                </form>
              </li>;
              return <li key={c.conversation_id} className={`hist-item${on ? ' is-on' : ''}`}>
                <button className={`hist-row${on ? ' is-on' : ''}`} onClick={() => onOpen(c.conversation_id)} aria-current={on ? 'true' : undefined} title={c.title}>
                  <span className="hist-q">{c.title || 'Không tên'}</span>
                  <time className="hist-t">{label(c)}</time>
                </button>
                <span className="hist-acts">
                  <button type="button" aria-label={`Đổi tên “${c.title}”`} title="Đổi tên" onClick={() => setEditing({ id: c.conversation_id, title: c.title })}><Pencil size={13} /></button>
                  <button type="button" aria-label={c.pinned ? `Bỏ ghim “${c.title}”` : `Ghim “${c.title}”`} title={c.pinned ? 'Bỏ ghim' : 'Ghim lên đầu'}
                    onClick={() => void run(c.conversation_id, { pinned: !c.pinned })}>{c.pinned ? <PinOff size={13} /> : <Pin size={13} />}</button>
                  <button type="button" className="is-danger" aria-label={`Xóa “${c.title}”`} title="Xóa" onClick={() => void remove(c)}><Trash2 size={13} /></button>
                </span>
              </li>;
            })}</ul>
          </section>)}
      </div>
    </section>
  );
});
