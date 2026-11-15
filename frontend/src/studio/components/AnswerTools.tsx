// Công cụ dưới mỗi câu trả lời: đánh giá hữu ích (👍/👎 kèm góp ý) và đèn báo độ tin cậy theo từng câu.
import React, { useState } from 'react';
import { ShieldCheck, ThumbsDown, ThumbsUp } from 'lucide-react';
import { GroundingResult, groundRun, Rating, sendFeedback } from '../services/api';

const LEVEL: Record<string, { label: string; hint: string }> = {
  supported: { label: 'Có căn cứ', hint: 'Câu trùng khớp rõ với một đoạn tài liệu, kể cả các con số.' },
  weak: { label: 'Cần kiểm tra', hint: 'Câu chỉ khớp một phần; có thể do diễn đạt lại. Nên mở đoạn nguồn để xem.' },
  unsupported: { label: 'Chưa thấy căn cứ', hint: 'Không tìm thấy đoạn tài liệu nào nói điều này. Không có nghĩa là sai, nhưng chưa có bằng chứng.' },
};

export function AnswerFeedback({ runId, initial, onSaved }: { runId: string; initial?: Rating; onSaved?: (r: Rating) => void }) {
  const [rating, setRating] = useState<Rating>(initial ?? 0);
  React.useEffect(() => { if (initial !== undefined) setRating(initial); }, [initial]);
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const save = async (next: Rating, text = '') => {
    const prev = rating; setRating(next); setError(null);
    try { await sendFeedback(runId, next, text); onSaved?.(next); } catch (e: any) { setRating(prev); setError(e.message); }
  };
  const vote = (r: 1 | -1) => {
    if (rating === r) { void save(0); setAsking(false); return; }
    void save(r); setAsking(r === -1);
  };
  return <>
    <span className="af" role="group" aria-label="Câu trả lời có hữu ích không" title="Đánh giá giúp nhóm phát triển cải thiện; quản trị viên xem được câu hỏi và câu trả lời đã đánh giá.">
      <button type="button" className={rating === 1 ? 'is-up' : ''} aria-pressed={rating === 1} onClick={() => vote(1)} title="Thích: câu trả lời hữu ích" aria-label="Thích câu trả lời"><ThumbsUp size={14} /></button>
      <button type="button" className={rating === -1 ? 'is-down' : ''} aria-pressed={rating === -1} onClick={() => vote(-1)} title="Không thích: chưa đúng hoặc chưa đủ" aria-label="Không thích câu trả lời"><ThumbsDown size={14} /></button>
    </span>
    {asking && <form className="af-note" onSubmit={e => { e.preventDefault(); void save(-1, note.trim()); setAsking(false); }}>
      <input value={note} onChange={e => setNote(e.target.value)} maxLength={500} placeholder="Chưa đúng ở đâu? (không bắt buộc)" aria-label="Góp ý cho câu trả lời" autoFocus />
      <button type="submit">Gửi góp ý</button>
      <button type="button" onClick={() => setAsking(false)}>Bỏ qua</button>
    </form>}
    {error && <span className="af-err" role="alert">{error}</span>}
  </>;
}

export function GroundingButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return <button type="button" aria-expanded={open} onClick={onToggle} title="Kiểm chứng: đối chiếu từng câu với tài liệu đã đọc" aria-label="Kiểm chứng với tài liệu"><ShieldCheck size={14} /></button>;
}

export function GroundingPanel({ runId, cache, setCache, onShowChunk }: {
  runId: string; cache: Record<string, GroundingResult | string>; setCache: React.Dispatch<React.SetStateAction<Record<string, GroundingResult | string>>>;
  onShowChunk: (id: string) => void;
}) {
  const data = cache[runId];
  React.useEffect(() => {
    if (data !== undefined) return;
    groundRun(runId).then(r => setCache(c => ({ ...c, [runId]: r }))).catch((e: Error) => setCache(c => ({ ...c, [runId]: e.message })));
  }, [runId, data, setCache]);
  if (data === undefined) return <div className="gr"><p className="muted-line"><span className="spin is-dark" />Đang đối chiếu với tài liệu…</p></div>;
  if (typeof data === 'string') return <div className="gr"><p className="note is-error">{data}</p></div>;
  const total = data.sentences.length;
  if (!total) return <div className="gr"><p className="gr-intro">Câu trả lời không có câu nội dung nào để đối chiếu.</p></div>;
  return (
    <div className="gr">
      <div className="gr-head">
        <p className="gr-intro">Đối chiếu {total} câu với {data.evidence_chunks} đoạn tài liệu mà lượt này đã đọc. Chạy tại máy, không gọi mô hình.</p>
        <div className="gr-bar" aria-hidden="true">{(['supported', 'weak', 'unsupported'] as const).map(l => data.counts[l] > 0 && <i key={l} className={`is-${l}`} style={{ flexGrow: data.counts[l] }} />)}</div>
        <div className="gr-legend">{(['supported', 'weak', 'unsupported'] as const).map(l => <span key={l} title={LEVEL[l].hint}><i className={`is-${l}`} /><b>{data.counts[l]}</b> {LEVEL[l].label}</span>)}</div>
      </div>
      <ol className="gr-list">
        {data.sentences.map((s, i) => (
          <li key={i} className={`is-${s.level}`}>
            <span className="gr-tag">{LEVEL[s.level].label}</span>
            <p>{s.text}</p>
            <div className="gr-src">
              {s.chunk_id && s.level !== 'unsupported' && <button type="button" onClick={() => onShowChunk(s.chunk_id!)} title="Xem đoạn tài liệu khớp nhất">
                {(s.source_name ?? '').replace(/\.[^.]+$/, '').replace(/_/g, ' ')} · đoạn {Number(s.chunk_id.split('_c').pop()) + 1}</button>}
              {s.missing_numbers.length > 0 && <small>Số không có trong đoạn nguồn: {s.missing_numbers.join(', ')}</small>}
            </div>
          </li>
        ))}
      </ol>
      <p className="gr-foot">Đối chiếu theo từ ngữ: câu diễn đạt lại có thể bị xếp “Cần kiểm tra”. Đây là công cụ hỗ trợ người đọc, không phải kết luận đúng sai.</p>
    </div>
  );
}
