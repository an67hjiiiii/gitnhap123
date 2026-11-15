// Phản hồi người dùng cho quản trị viên: mọi câu trả lời đã được chấm 👍/👎, kèm câu hỏi, góp ý và trích câu trả lời.
import React, { useEffect, useMemo, useState } from 'react';
import { Download, ThumbsDown, ThumbsUp } from 'lucide-react';
import { adminFeedback, AdminFeedbackItem } from '../services/api';
import { StudioModal } from './StudioModal';
import { csvCell, download } from './analysis/shared';

export function AdminFeedbackModal({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<{ up: number; down: number; items: AdminFeedbackItem[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'down' | 'up'>('down');
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { adminFeedback().then(setData).catch(e => setError(e.message)); }, []);
  const rows = useMemo(() => (data?.items || []).filter(i => filter === 'all' || (filter === 'up' ? i.rating === 1 : i.rating === -1)), [data, filter]);
  const exportCsv = () => data && download('phan-hoi-nguoi-dung.csv',
    ['Thời điểm,Người dùng,Đánh giá,Câu hỏi,Góp ý,Trạng thái,Câu trả lời', ...data.items.map(i => [new Date(i.created_at).toLocaleString('vi-VN'), i.user, i.rating === 1 ? 'Hữu ích' : 'Chưa đúng/đủ', i.query, i.note, i.status, i.answer].map(csvCell).join(','))].join('\n'), 'text/csv');
  const total = (data?.up || 0) + (data?.down || 0);

  return (
    <StudioModal labelId="fb-admin" icon={<ThumbsUp size={18} />} title="Phản hồi người dùng"
      subtitle={data ? `${total} đánh giá · ${data.up} hữu ích · ${data.down} chưa đúng hoặc chưa đủ${total ? ` · ${Math.round((data.up / total) * 100)}% hữu ích` : ''}` : 'Đang tải…'}
      onClose={onClose}
      toolbar={<div className="tv-seg" role="group" aria-label="Lọc đánh giá">
        {(['down', 'up', 'all'] as const).map(f => <button key={f} className={filter === f ? 'is-on' : ''} onClick={() => setFilter(f)}>{{ down: 'Cần sửa (👎)', up: 'Hữu ích (👍)', all: 'Tất cả' }[f]}</button>)}
      </div>}
      footer={<><span className="mo-note">Khi người dùng đánh giá, câu hỏi và câu trả lời của lượt đó hiện ở đây để nhóm phát triển cải thiện.</span>
        {data && data.items.length > 0 && <button className="btn btn-ghost" onClick={exportCsv}><Download size={15} />Tải (.csv)</button>}
        <button className="btn btn-dark" onClick={onClose}>Đóng</button></>}>
      {error ? <p className="note is-error">{error}</p> : !data ? <p className="muted-line is-center"><span className="spin is-dark" />Đang tải phản hồi…</p>
        : rows.length === 0 ? <div className="empty">{filter === 'down' ? 'Chưa có câu trả lời nào bị chấm 👎.' : 'Chưa có đánh giá nào.'}</div>
        : <ul className="fb-list">{rows.map(i => <li key={`${i.run_id}-${i.user}`} className={i.rating === 1 ? 'is-up' : 'is-down'}>
          <div className="fb-head">
            <span className="fb-rate">{i.rating === 1 ? <ThumbsUp size={14} /> : <ThumbsDown size={14} />}</span>
            <b>{i.query || '(không có câu hỏi)'}</b>
            <small>{i.user || 'Không rõ'} · {new Date(i.created_at).toLocaleString('vi-VN')}{i.status ? ` · ${i.status}` : ''}</small>
          </div>
          {i.note && <p className="fb-note">“{i.note}”</p>}
          {i.answer && <button type="button" className="fb-toggle" aria-expanded={open === i.run_id} onClick={() => setOpen(open === i.run_id ? null : i.run_id)}>{open === i.run_id ? 'Ẩn câu trả lời' : 'Xem câu trả lời'}</button>}
          {open === i.run_id && <pre className="chunk-pre">{i.answer}</pre>}
        </li>)}</ul>}
    </StudioModal>
  );
}
