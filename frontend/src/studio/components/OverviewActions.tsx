// Tổng quan có hành động (Đợt 9): tiếp tục việc đang dở, cảnh báo kho, đơn chờ duyệt, tài liệu mới thay bản cũ.
// Mỗi thẻ dẫn tới đúng chỗ xử lý; số lấy từ máy chủ; không có gì thì thẻ nói rõ "không có", không bịa.
import React, { useEffect, useState } from 'react';
import { ArrowRight, ClipboardList, FileWarning, GitCompareArrows, MessageSquareText } from 'lucide-react';
import { getNotifications, libraryQuality, listRequests } from '../services/api';
import type { NavigationTab } from '../types';
import { serverDate } from '../utils/time';

type Conv = { conversation_id: string; title: string; updated_at: string };
const ago = (iso: string) => {
  const m = Math.round((Date.now() - serverDate(iso).getTime()) / 60000);
  return m < 1 ? 'vừa xong' : m < 60 ? `${m} phút trước` : m < 1440 ? `${Math.round(m / 60)} giờ trước` : `${Math.round(m / 1440)} ngày trước`;
};

export const OverviewActions: React.FC<{ recent: Conv[]; spaceId?: string; onOpenConversation: (id: string) => void; onGo: (t: NavigationTab) => void }> = ({ recent, spaceId, onOpenConversation, onGo }) => {
  const [issues, setIssues] = useState<number | null>(null);
  const [pending, setPending] = useState<number | null>(null);
  const [watch, setWatch] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    libraryQuality().then(q => alive && setIssues(q.docs.reduce((n, d) => n + d.issues.filter(i => i.level !== 'low').length, 0) + q.duplicates.length)).catch(() => alive && setIssues(null));
    getNotifications().then(r => alive && setWatch(r.items.filter(n => n.kind === 'doc_watch' && !n.read).length)).catch(() => alive && setWatch(null));
    if (spaceId) listRequests(spaceId).then(r => alive && setPending(r.to_me.filter(x => x.status === 'PENDING' && x.can_decide).length)).catch(() => alive && setPending(null));
    else setPending(null);
    return () => { alive = false; };
  }, [spaceId]);
  const last = recent[0];
  const card = (key: string, I: typeof ClipboardList, tone: string, title: string, body: React.ReactNode, cta: string, go: () => void, quiet = false) =>
    <button key={key} type="button" className={`ova-card is-${tone}${quiet ? ' is-quiet' : ''}`} onClick={go}>
      <span className="ova-ico"><I size={18} /></span><b>{title}</b><span className="ova-body">{body}</span><span className="ova-cta">{cta}<ArrowRight size={14} /></span>
    </button>;
  return (
    <section className="ova" aria-label="Việc cần làm ngay">
      {card('continue', MessageSquareText, 'blue', 'Tiếp tục',
        last ? <>“{last.title || 'Không tên'}” · {ago(last.updated_at)}</> : 'Chưa có cuộc trò chuyện nào.',
        last ? 'Mở cuộc trò chuyện' : 'Hỏi câu đầu tiên', () => last ? onOpenConversation(last.conversation_id) : onGo('orchestration'), !last)}
      {card('kb', FileWarning, issues ? 'amber' : 'green', 'Cảnh báo kho',
        issues === null ? 'Chưa tải được.' : issues ? `${issues} vấn đề: tài liệu trùng, quá ngắn hoặc không đọc được chữ.` : 'Không có vấn đề chất lượng nào.',
        'Mở Tài liệu', () => onGo('library'), !issues)}
      {spaceId && card('req', ClipboardList, pending ? 'violet' : 'green', 'Đơn chờ bạn duyệt',
        pending === null ? 'Chưa tải được.' : pending ? `${pending} đơn đang chờ.` : 'Không có đơn nào chờ bạn.',
        'Mở Đơn từ', () => onGo('tasks'), !pending)}
      {card('watch', GitCompareArrows, watch ? 'teal' : 'green', 'Tài liệu mới thay bản cũ',
        watch === null ? 'Chưa tải được.' : watch ? `${watch} thông báo chưa xem: bản mới thay thế hoặc mâu thuẫn với tài liệu cũ.` : 'Không có thông báo mới.',
        'So sánh phiên bản', () => onGo(watch ? 'results' : 'compare'), !watch)}
    </section>
  );
};
