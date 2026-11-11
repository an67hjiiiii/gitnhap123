import { metric, percent } from '../utils/measurement';
import React, { useState, useEffect, useMemo } from 'react';
import { RefreshCw, Search, Clock, X, AlertCircle } from 'lucide-react';
import { ModeExecutionResult, TelemetryRecord } from '../types';
import { serverDate } from '../utils/time';
import { getRuntimeConfig } from '../services/api';
import { useRobotAssistant } from './robot/RobotContext';

interface BenchmarkLabProps {
  resultsMap: Record<string, ModeExecutionResult>;
  telemetryLogs: TelemetryRecord[];
  onRefreshTelemetry: () => void;
  onRunAblation?: (query: string) => Promise<void>;
  isAblationRunning?: boolean;
}

type SubTab = 'ablation' | 'configs' | 'telemetry';

const METHODS = [
  { id: 'vanilla_rag', key: 'A', name: 'Vanilla RAG', desc: 'Điều kiện A: một lượt truy xuất, một lần sinh.' },
  { id: 'naive_multi_agent', key: 'B', name: 'Multi-Agent cơ bản', desc: 'Điều kiện B: có chia việc, chưa tối ưu.' },
  { id: 'proposed_adaptive', key: 'C', name: 'Điều phối đầy đủ', desc: 'Điều kiện C: lập kế hoạch, chuẩn hóa, tối ưu ngữ cảnh.' },
] as const;
const PRESETS = [
  'Xử lý Stripe Webhook, cơ chế Idempotency Key và khóa lạc quan (Optimistic Locking).',
  'Thiết kế phân quyền RBAC và cách ly dữ liệu Multi-Tenant bằng PostgreSQL RLS.',
  'Mẫu thiết kế Transactional Outbox đồng bộ phân tán với Kafka.',
];
const MODE_KEY: Record<string, string> = { A: 'A', B: 'B', C: 'C', 'C-P': 'CP', 'C-N': 'CN', 'C-O': 'CO' };
// Trạng thái CAP1: lượt bị từ chối vẫn có số đo nhưng không phải câu trả lời hoàn chỉnh.
const STATUS_VI: Record<string, string> = { COMPLETE: 'Đủ bằng chứng', PARTIAL: 'Một phần', NO_EVIDENCE: 'Không có bằng chứng', FAILED: 'Thất bại' };
const num = (v: number | null | undefined, digits = 0) => v == null ? null : v.toLocaleString('vi-VN', { maximumFractionDigits: digits });

export const BenchmarkLab: React.FC<BenchmarkLabProps> = ({ resultsMap, telemetryLogs, onRefreshTelemetry, onRunAblation, isAblationRunning = false }) => {
  const [tab, setTab] = useState<SubTab>('ablation');
  const [query, setQuery] = useState(PRESETS[0]);
  const [runtimeCfg, setRuntimeCfg] = useState<Record<string, any> | null>(null);
  const [loadingConfigs, setLoadingConfigs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const { setState: setRobotState, speak: robotSpeak } = useRobotAssistant();

  useEffect(() => { if (tab === 'configs') void loadConfigs(); }, [tab]);
  useEffect(() => {
    if (!isAblationRunning) return;
    const start = performance.now(); setElapsed(0);
    const t = window.setInterval(() => setElapsed(Math.floor((performance.now() - start) / 1000)), 1000);
    return () => window.clearInterval(t);
  }, [isAblationRunning]);

  const loadConfigs = async () => {
    setLoadingConfigs(true);
    try { setRuntimeCfg(await getRuntimeConfig()); } catch (err) { console.error('Không tải được cấu hình đang chạy:', err); setRuntimeCfg(null); } finally { setLoadingConfigs(false); }
  };
  const runAblation = async () => {
    if (!query.trim() || isAblationRunning || !onRunAblation) return;
    setRobotState('working');
    robotSpeak('Đang chạy lần lượt Vanilla RAG, Multi-Agent cơ bản và Điều phối thích ứng trên cùng câu hỏi…');
    try { await onRunAblation(query); setRobotState('completed'); robotSpeak('Đã chạy xong ba phương pháp. Kết quả nằm trong bảng so sánh.'); }
    catch (err: any) { setRobotState('error'); robotSpeak(`Lỗi khi chạy đối chứng: ${err.message}`); }
  };

  const logs = useMemo(() => telemetryLogs.filter(l =>
    (filter === 'all' || l.execution_mode === filter) &&
    (!search.trim() || l.user_query.toLowerCase().includes(search.toLowerCase()) || String(l.id).includes(search))
  ), [telemetryLogs, filter, search]);

  const rows: { label: string; get: (r: ModeExecutionResult) => string | null; only?: string }[] = [
    { label: 'Trạng thái', get: r => r.raw?.status ? (STATUS_VI[r.raw.status] ?? r.raw.status) : null },
    { label: 'Độ trễ', get: r => r.latency_ms == null ? null : `${num(r.latency_ms / 1000, 1)} giây` },
    { label: 'Tổng token', get: r => num(r.total_tokens) },
    { label: 'Token tiết kiệm', get: r => r.tokens_saved == null ? null : `${metric(r.tokens_saved)} (${percent(r.token_saving_ratio, 1)})`, only: 'proposed_adaptive' },
    { label: 'Độ phủ nhiệm vụ', get: r => r.task_coverage == null ? null : percent(r.task_coverage, 0) },
    { label: 'CPU / ΔRAM', get: r => r.cpu_percent == null ? null : `${num(r.cpu_percent, 1)}% / ${num(r.ram_delta_mb, 1)} MB` },
  ];
  const bars: { label: string; key: 'total_tokens' | 'latency_ms'; fmt: (v: number) => string }[] = [
    { label: 'Tổng token', key: 'total_tokens', fmt: v => num(v)! },
    { label: 'Độ trễ', key: 'latency_ms', fmt: v => `${num(v / 1000, 1)} giây` },
  ];

  return (
    <main className="pg">
      <div className="pg-col">
        <header className="pg-head">
          <div><h1>Thực nghiệm</h1><p>So sánh ba phương pháp trên cùng một yêu cầu, quản lý cấu hình và xem nhật ký lượt chạy.</p></div>
          <button className="btn btn-ghost" onClick={onRefreshTelemetry}><RefreshCw size={15} />Làm mới</button>
        </header>

        <div className="tabs" role="tablist" aria-label="Mục thực nghiệm">
          <button role="tab" aria-selected={tab === 'ablation'} className={tab === 'ablation' ? 'is-on' : ''} onClick={() => setTab('ablation')}>Đối chiếu</button>
          <button role="tab" aria-selected={tab === 'configs'} className={tab === 'configs' ? 'is-on' : ''} onClick={() => setTab('configs')}>Cấu hình</button>
          <button role="tab" aria-selected={tab === 'telemetry'} className={tab === 'telemetry' ? 'is-on' : ''} onClick={() => setTab('telemetry')}>Nhật ký <span className="tab-n">{telemetryLogs.length}</span></button>
        </div>

        {error && <div className="note is-error"><AlertCircle size={16} /><span>{error}</span><button className="note-x" onClick={() => setError(null)} aria-label="Đóng thông báo"><X size={14} /></button></div>}

        {tab === 'ablation' && <>
          <div className={`composer${isAblationRunning ? ' is-busy' : ''}`}>
            <textarea aria-label="Yêu cầu chạy đối chứng" rows={2} value={query} onChange={e => setQuery(e.target.value)} placeholder="Nhập yêu cầu kỹ thuật để chạy cả ba phương pháp" />
            <div className="composer-bar">
              <div className="chips">{PRESETS.map((p, i) => <button key={i} className={`chip${query === p ? ' is-on' : ''}`} onClick={() => setQuery(p)}>Kịch bản {i + 1}</button>)}</div>
              <button className="btn btn-dark" onClick={runAblation} disabled={isAblationRunning || !query.trim() || !onRunAblation}>
                {isAblationRunning ? <><span className="spin" />Đang chạy · {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}</> : 'Chạy đối chứng'}
              </button>
            </div>
          </div>
          {isAblationRunning && <p className="muted-line"><Clock size={14} />Ba phương pháp chạy lần lượt trên mô hình cục bộ, có thể mất vài phút. Hệ thống chưa báo tiến độ từng bước.</p>}

          <div className="cmp">
            {METHODS.map(m => {
              const r = resultsMap[m.id];
              return (
                <section key={m.id} className={`cmp-col${m.key === 'C' ? ' is-a' : ''}`}>
                  <div className="cmp-head"><b className={`mode-key${m.key === 'C' ? ' is-a' : ''}`}>{m.key}</b><div><h3>{m.name}</h3><p>{m.desc}</p></div></div>
                  <dl>
                    {rows.map(row => {
                      const v = row.only && row.only !== m.id ? '—' : r ? row.get(r) : null;
                      return <div key={row.label}><dt>{row.label}</dt><dd className={v == null || v === '—' ? 'is-muted' : ''}>{v ?? (r ? 'Chưa đo' : 'Chờ chạy')}</dd></div>;
                    })}
                  </dl>
                </section>
              );
            })}
          </div>

          <div className="bars">
            {bars.map(b => {
              const max = Math.max(1, ...METHODS.map(m => resultsMap[m.id]?.[b.key] ?? 0));
              return (
                <section key={b.key}>
                  <h3>{b.label}</h3>
                  {METHODS.map(m => {
                    const v = resultsMap[m.id]?.[b.key];
                    return <div key={m.id} className="bar-row"><span>{m.key}</span><b><i className={m.key === 'C' ? 'is-a' : ''} style={{ width: v ? `${Math.max(2, (v / max) * 100)}%` : 0 }} /></b><em>{v ? b.fmt(v) : 'Chờ chạy'}</em></div>;
                  })}
                </section>
              );
            })}
          </div>
          <p className="footnote">Số liệu do API nguyên mẫu trả về cho lượt chạy vừa rồi. Độ phủ và mức tiết kiệm token chưa được thẩm định; một lượt chạy không phải kết quả thực nghiệm.</p>
        </>}

        {tab === 'configs' && <>
          <div className="row-head"><p>Backend CAP1 cấu hình bằng biến môi trường. Mỗi lượt chạy ghi <b>config_hash</b> nên biết chính xác cấu hình đã dùng (tái lập).</p></div>
          {loadingConfigs ? <p className="muted-line"><span className="spin is-dark" />Đang tải cấu hình…</p> : !runtimeCfg ? <div className="empty">Không tải được cấu hình đang chạy.</div> : (
            <div className="tbl">
              <table>
                <thead><tr><th>Tham số</th><th>Giá trị</th></tr></thead>
                <tbody>{Object.entries(runtimeCfg).map(([k, v]) => (
                  <tr key={k}><td><b>{k}</b></td><td>{Array.isArray(v) ? v.join(', ') : String(v)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </>}

        {tab === 'telemetry' && <>
          <div className="row-head">
            <div className="seg">{[['all', 'Tất cả'], ['C', 'C'], ['B', 'B'], ['A', 'A'], ['C-P', 'C-P'], ['C-N', 'C-N'], ['C-O', 'C-O']].map(([k, l]) => <button key={k} className={filter === k ? 'is-on' : ''} onClick={() => setFilter(k)} aria-pressed={filter === k}>{l}</button>)}</div>
            <label className="search"><Search size={14} /><span className="sr">Lọc theo yêu cầu</span><input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Tìm yêu cầu hoặc mã" /></label>
          </div>
          <p className="muted-line">Lượt chạy mới ghi số đo thật lúc chạy (token, thời gian). Chất lượng và tiết kiệm token còn chờ đánh giá; số liệu cũ chưa xác minh không dùng để kết luận.</p>
          {logs.length === 0 ? <div className="empty">Chưa có lượt chạy phù hợp.</div> : (
            <div className="tbl">
              <table>
                <thead><tr><th>#</th><th>Phương pháp</th><th>Độ trễ</th><th>Token</th><th>Tiết kiệm</th><th>Độ phủ</th><th>Yêu cầu</th><th>Thời điểm</th></tr></thead>
                <tbody>{logs.map(l => (
                  <tr key={`${l.record_source}-${l.id}`}>
                    <td className="is-muted" title={String(l.id)}>{String(l.id).slice(-6)}</td>
                    <td><span className="mode-pill"><b className={`mode-key${MODE_KEY[l.execution_mode] === 'C' ? ' is-a' : ''}`}>{MODE_KEY[l.execution_mode] ?? '?'}</b>{l.record_source === 'legacy' && <em>cũ, chưa xác minh</em>}</span></td>
                    <td>{l.latency_ms == null ? <span className="is-muted">Chưa đo</span> : `${num(l.latency_ms / 1000, 1)} giây`}</td>
                    <td>{l.total_tokens == null ? <span className="is-muted">Chưa đo</span> : num(l.total_tokens)}</td>
                    <td className={l.tokens_saved == null ? 'is-muted' : ''}>{metric(l.tokens_saved)}</td>
                    <td className={l.task_coverage == null ? 'is-muted' : ''}>{percent(l.task_coverage, 0)}</td>
                    <td className="is-query" title={l.user_query}>{l.user_query}</td>
                    <td className="is-muted">{serverDate(l.created_at).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </>}
      </div>
    </main>
  );
};
