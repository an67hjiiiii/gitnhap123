// Đợt 5 (23/11): dòng thời gian 2D "ai làm gì, mất bao lâu" trong mỗi câu trả lời. Bấm một người: văn phòng tua tới bước đó.
import type { TimelineGroup } from './timeline';
import { fmtMs } from './timeline';

export function RunTimeline({ groups, onSeek, live = false }: { groups: TimelineGroup[]; onSeek: (eventIndex: number) => void; live?: boolean }) {
  if (!groups.length) return null;
  return (
    <div className="ws-tl">
      <span className="ws-tl-title" title={live ? 'Thời gian đo lúc trình duyệt nhận sự kiện' : 'Thời gian lấy từ mốc đã lưu của lượt chạy'}>Ai làm gì</span>
      <ol aria-label="Ai làm gì trong lượt này">
        {groups.map((g, i) => (
          <li key={`${g.actor}-${i}`}>
            <button type="button" className={`is-${g.state}`} onClick={() => onSeek(g.eventIndex)}
              title={`${g.steps.join(' → ')}${g.state === 'fail' ? ' (chưa qua)' : ''}. Bấm để xem trong văn phòng`}>
              <b>{g.who}</b>{g.ms !== null && <span>{g.state === 'now' ? 'đang làm' : fmtMs(g.ms)}</span>}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
