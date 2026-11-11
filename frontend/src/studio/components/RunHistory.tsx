import React, { useState } from 'react';
import { History, Search } from 'lucide-react';
import { TelemetryRecord } from '../types';
import { serverDate } from '../utils/time';
import { CONDITION_LABEL } from '../services/adapt';

interface RunHistoryProps {
  runs: TelemetryRecord[];
  activeRunId: number | null;
  loadingRunId: number | null;
  onOpenRun: (run: TelemetryRecord) => void;
}

const MODE_KEY: Record<string, string> = { A: 'A', B: 'B', C: 'C', 'C-P': 'CP', 'C-N': 'CN', 'C-O': 'CO' };
const MODE_NAME: Record<string, string> = CONDITION_LABEL;

function when(s: string) {
  const d = serverDate(s), now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay ? d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
}

// Lịch sử trò chuyện: các lượt chạy đã lưu của không gian hiện tại (API /telemetry, chỉ bản ghi research_v2).
export const RunHistory: React.FC<RunHistoryProps> = ({ runs, activeRunId, loadingRunId, onOpenRun }) => {
  const [q, setQ] = useState('');
  const saved = runs.filter(r => r.record_source !== 'legacy');
  const shown = q.trim() ? saved.filter(r => r.user_query.toLowerCase().includes(q.trim().toLowerCase())) : saved;
  return (
    <section className="hist" aria-labelledby="hist-title">
      <div className="hist-head"><History size={14} /><h2 id="hist-title">Lịch sử trò chuyện</h2>{saved.length > 0 && <span className="kb-count">{saved.length}</span>}</div>
      {saved.length > 4 && <label className="kb-search"><Search size={14} /><span className="sr">Tìm trong lịch sử</span>
        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm yêu cầu cũ" /></label>}
      <ul className="hist-list">
        {saved.length === 0 ? <li className="kb-none">Chưa có lượt chạy nào được lưu trong không gian này.</li>
          : shown.length === 0 ? <li className="kb-none">Không có yêu cầu khớp.</li>
          : shown.map(r => (
            <li key={r.id}>
              <button className={`hist-row${activeRunId === r.id ? ' is-on' : ''}`} onClick={() => onOpenRun(r)} disabled={loadingRunId === r.id}
                aria-current={activeRunId === r.id ? 'true' : undefined}
                title={`${r.user_query}\n${MODE_NAME[r.execution_mode] ?? r.execution_mode} · ${serverDate(r.created_at).toLocaleString('vi-VN')}`}>
                <b className={`mode-key${MODE_KEY[r.execution_mode] === 'C' ? ' is-a' : ''}`} aria-label={MODE_NAME[r.execution_mode]}>{MODE_KEY[r.execution_mode] ?? '?'}</b>
                <span className="hist-q">{loadingRunId === r.id ? 'Đang mở…' : r.user_query}</span>
                <time className="hist-t" dateTime={serverDate(r.created_at).toISOString()}>{when(r.created_at)}</time>
              </button>
            </li>
          ))}
      </ul>
    </section>
  );
};
