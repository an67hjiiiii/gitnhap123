// Tổng quan: số liệu sử dụng thật của tài khoản (tài liệu, lượt chạy, token, độ trễ, phản hồi), tình trạng hệ thống
// và nhật ký hoạt động có phân trang. Mọi con số lấy từ dữ liệu đã lưu; chưa có thì hiện "Chưa có"/"Chưa đo", không ước lượng.
// Biểu đồ vẽ bằng SVG (không thêm thư viện): vòng tỉ lệ, vùng xếp lớp theo ngày, bong bóng, bản đồ nhiệt, ô chủ đề.
// Màu: trạng thái dùng bảng trạng thái cố định (luôn kèm nhãn chữ); cách trả lời dùng màu nhóm thứ tự cố định (đã kiểm CVD);
// bản đồ nhiệt một sắc xanh nhạt -> đậm.
// Hiệu năng: số liệu nhớ trong phiên (quay lại trang hiện ngay, tải mới ở nền); trang chỉ vẽ lại khi trường sức khỏe nó dùng đổi.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, BarChart3, CalendarDays, ChevronLeft, ChevronRight, Clock3, Coins, Cpu, Download, FileQuestion, FileText, Gauge,
  LineChart, MessageCircleQuestion, MessageSquare, Network, RefreshCw, Save, Search, ShieldCheck, ThumbsUp, Timer, Trash2,
  TrendingDown, TrendingUp, Upload, UserCog, Wand2,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { ActivityRow, getActivity, getActivityPage, getOverview, Overview } from '../services/api';
import { HealthResponse } from '../types';
import { csvCell, download, EmptyState, fmtSeconds, ToolHeader } from './analysis/shared';
import { CountUp } from './StudioMotion';

const COND: Record<string, string> = { A: 'A · Vanilla RAG', B: 'B · Multi-Agent cơ bản', C: 'C · Điều phối đầy đủ', 'C-P': 'C-P', 'C-N': 'C-N', 'C-O': 'C-O' };
// màu nhóm theo thứ tự cố định (màu đi theo cách trả lời, không theo thứ hạng)
const COND_COLOR: Record<string, string> = { A: '#2a78d6', B: '#eb6834', C: '#1baf7a', 'C-P': '#eda100', 'C-N': '#e87ba4', 'C-O': '#6250d6' };
const STATUS = [
  { key: 'COMPLETE', label: 'Đủ bằng chứng', color: '#0ca30c' },
  { key: 'PARTIAL', label: 'Một phần', color: '#fab219' },
  { key: 'NO_EVIDENCE', label: 'Không có bằng chứng', color: '#9aa4b2' },
  { key: 'FAILED', label: 'Thất bại', color: '#d03b3b' },
] as const;
const HEAT = ['#eef4fc', '#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95'];
const WEEKDAY = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];
const REPORT: Record<string, string> = {
  traceability: 'Truy vết yêu cầu', design: 'Gói thiết kế', security_review: 'Rà soát bảo mật', consistency: 'Kiểm tra mâu thuẫn',
  evaluation: 'Phòng đánh giá', eval_set: 'Bộ câu hỏi đánh giá', doc_profile: 'Hồ sơ tài liệu', doc_compare: 'So sánh phiên bản', mindmap: 'Sơ đồ tư duy',
  req_quality: 'Chất lượng yêu cầu',
};
const dayLabel = (iso: string) => { const [, m, d] = iso.split('-'); return `${Number(d)}/${Number(m)}`; };
const pctNum = (a: number, b: number) => (b ? Math.round((a / b) * 100) : null);
const docName = (n: string) => n.replace(/\.[^.]+$/, '').replace(/_/g, ' ');
const PAGE = 15;
const tfmt = new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const dfmt = new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });

/** Số kiểu "16,7 s": phần nguyên đậm, phần thập phân và đơn vị nhạt hơn (như các bảng điều khiển mẫu). */
function Num({ text }: { text: string }) {
  const m = text.match(/^([^,]*)(,.*)?$/);
  return <>{m?.[1]}{m?.[2] && <small className="ov-dec">{m[2]}</small>}</>;
}

/** Biểu tượng tròn đặt trước tiêu đề thẻ. */
const Ico = ({ I }: { I: LucideIcon }) => <span className="ov-ico" aria-hidden="true"><I size={15} /></span>;

/** Biểu tượng theo loại thao tác trong nhật ký (đoán theo tên thao tác). */
function actionIcon(action: string): LucideIcon {
  const a = action.toLowerCase();
  if (/xóa/.test(a)) return Trash2;
  if (/nạp|tải lên/.test(a)) return Upload;
  if (/hỏi|trò chuyện/.test(a)) return MessageSquare;
  if (/sơ đồ/.test(a)) return Network;
  if (/báo cáo|lưu/.test(a)) return Save;
  if (/tài khoản|mật khẩu|vai trò|phiên/.test(a)) return UserCog;
  if (/hồ sơ|tài liệu|truy vết|yêu cầu/.test(a)) return FileText;
  if (/thiết kế|rà soát|mâu thuẫn|đánh giá|so sánh/.test(a)) return Wand2;
  return Activity;
}

/** Đường cong mượt đi qua mọi điểm và không vọt quá điểm kề (nội suy đơn điệu Fritsch–Carlson): không tạo đỉnh/đáy giả. */
function smoothPath(pts: [number, number][]): string {
  const n = pts.length;
  if (n < 2) return n ? `M${pts[0][0]} ${pts[0][1]}` : '';
  const m: number[] = [], t: number[] = [];
  for (let i = 0; i < n - 1; i++) m.push((pts[i + 1][1] - pts[i][1]) / (pts[i + 1][0] - pts[i][0]));
  t.push(m[0]);
  for (let i = 1; i < n - 1; i++) t.push(m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2);
  t.push(m[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
    const a = t[i] / m[i], b = t[i + 1] / m[i], q = a * a + b * b;
    if (q > 9) { const k = 3 / Math.sqrt(q); t[i] = k * a * m[i]; t[i + 1] = k * b * m[i]; }
  }
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const dx = (pts[i + 1][0] - pts[i][0]) / 3;
    d += `C${(pts[i][0] + dx).toFixed(1)} ${(pts[i][1] + t[i] * dx).toFixed(1)} ${(pts[i + 1][0] - dx).toFixed(1)} ${(pts[i + 1][1] - t[i + 1] * dx).toFixed(1)} ${pts[i + 1][0].toFixed(1)} ${pts[i + 1][1].toFixed(1)}`;
  }
  return d;
}

// Số liệu nhớ trong phiên: quay lại trang Tổng quan hiện ngay bản gần nhất rồi tải mới ở nền.
let cache: { data: Overview; at: number } | null = null;

const OverviewViewImpl: React.FC<{ health?: HealthResponse | null; userName?: string; actions?: React.ReactNode }> = ({ health, userName, actions }) => {
  const [data, setData] = useState<Overview | null>(cache?.data ?? null);
  const [at, setAt] = useState<number | null>(cache?.at ?? null);
  const [range, setRange] = useState<7 | 14>(14);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const live = useRef(true);

  const refresh = async () => {
    setBusy(true); setError(null);
    try { const d = await getOverview(); cache = { data: d, at: Date.now() }; if (live.current) { setData(d); setAt(cache.at); } }
    catch (e: any) { if (live.current) setError(e.message); } finally { if (live.current) setBusy(false); }
  };
  useEffect(() => { live.current = true; void refresh(); return () => { live.current = false; }; }, []);

  const s = data?.runs_by_status || {};
  const fb = data?.feedback;
  const complete = pctNum(s.COMPLETE || 0, data?.runs || 0);
  const helpful = fb ? pctNum(fb.up, fb.up + fb.down) : null;
  const daily = data?.daily || [];
  const last7 = daily.slice(-7).reduce((n, d) => n + d.runs, 0), prev7 = daily.slice(-14, -7).reduce((n, d) => n + d.runs, 0);
  const delta = prev7 ? Math.round(((last7 - prev7) / prev7) * 100) : null;
  const first = userName?.trim().split(/\s+/).slice(-1)[0];

  return (
    <main className="pg tl tone-overview">
      <div className="pg-col tv-col">
        <ToolHeader Icon={BarChart3} title="Tổng quan"
          desc={`${first ? `Chào ${first}. ` : ''}Hệ thống đã được dùng thế nào: kho tài liệu, các lượt hỏi và phân tích, chi phí token, thời gian trả lời, mức hài lòng và nhật ký thao tác.`}
          right={<div className="ov-head-r">
            {daily.length > 1 && <span className="ov-range"><CalendarDays size={14} aria-hidden="true" />14 ngày gần nhất · {dayLabel(daily[0].date)}–{dayLabel(daily[daily.length - 1].date)}</span>}
            <button className="btn btn-ghost" onClick={refresh} disabled={busy}>{busy ? <span className="spin is-dark" /> : <RefreshCw size={15} />}Làm mới</button>
            {at && <span className="ov-updated" aria-live="polite">Cập nhật lúc {tfmt.format(at)}</span>}
          </div>} />
        {actions}
        {error && <p className="note is-error" role="alert">{error}</p>}
        {!data ? (busy ? <p className="muted-line"><span className="spin is-dark" />Đang tải số liệu…</p> : null) : <>
          <div className="dp-kpis is-6 ov-kpis">
            <div className="ov-lead"><b><CountUp value={data.runs} /></b><span>lượt hỏi và phân tích</span>
              <em className="ov-badge is-glass">{delta == null ? `7 ngày qua: ${last7.toLocaleString('vi-VN')} lượt` : <>{delta >= 0 ? <TrendingUp size={13} aria-hidden="true" /> : <TrendingDown size={13} aria-hidden="true" />}{delta > 0 ? '+' : ''}{delta}% so với 7 ngày trước</>}</em>
              <Spark days={data.daily} /></div>
            <Kpi I={FileText} label="Kho tài liệu" value={<CountUp value={data.sources} />} unit="tài liệu" ctx={`${data.chunks.toLocaleString('vi-VN')} đoạn`} />
            <Kpi I={ShieldCheck} label="Đủ bằng chứng" value={complete == null ? 'Chưa có' : `${complete}%`} ctx={`${(s.COMPLETE || 0).toLocaleString('vi-VN')} / ${data.runs.toLocaleString('vi-VN')} lượt`} ring={{ value: complete, color: '#0ca30c' }} />
            <Kpi I={Coins} label="Token mỗi lượt" value={data.tokens_avg != null ? data.tokens_avg.toLocaleString('vi-VN') : 'Chưa đo'} ctx={data.tokens_total != null ? `tổng ${data.tokens_total.toLocaleString('vi-VN')}` : 'trung bình mỗi lượt'} />
            <Kpi I={Timer} label="Thời gian trả lời" value={data.latency_avg_ms != null ? <Num text={`${fmtSeconds(data.latency_avg_ms)} s`} /> : 'Chưa đo'}
              ctx={data.latency_p50_ms != null ? `trung vị ${fmtSeconds(data.latency_p50_ms)}\u00a0s · p95 ${fmtSeconds(data.latency_p95_ms ?? 0)}\u00a0s` : 'trung bình mỗi lượt'} />
            <Kpi I={ThumbsUp} label="Hữu ích" value={helpful == null ? 'Chưa có' : `${helpful}%`} ctx={fb && fb.up + fb.down ? `${fb.up} hữu ích · ${fb.down} chưa đạt` : 'chưa có đánh giá'} ring={{ value: helpful, color: '#2a78d6' }}
              extra={fb && fb.up + fb.down ? <span className="ov-split" role="img" aria-label={`${fb.up} đánh giá hữu ích, ${fb.down} chưa đạt`}><i className="is-up" style={{ flexGrow: fb.up }} /><i className="is-down" style={{ flexGrow: fb.down }} /></span> : undefined} />
          </div>

          {data.runs > 0 ? <>
            <div className="ov-grid ov-grid-2-3">
              <section className="dz-card">
                <header><h3><Ico I={ShieldCheck} />Chất lượng câu trả lời</h3><small className="is-muted">{data.runs.toLocaleString('vi-VN')} lượt</small></header>
                <Donut parts={STATUS.map(x => ({ ...x, value: s[x.key] || 0 }))} total={data.runs}
                  foot={data.tokens_total != null ? <>tổng {data.tokens_total.toLocaleString('vi-VN')} token</> : undefined} />
              </section>
              <section className="dz-card">
                <header><h3><Ico I={LineChart} />Lượt hỏi mỗi ngày</h3>
                  <span className="ov-seg" role="group" aria-label="Khoảng thời gian">{([7, 14] as const).map(r => <button key={r} type="button" aria-pressed={range === r} className={range === r ? 'is-on' : ''} onClick={() => setRange(r)}>{r} ngày</button>)}</span></header>
                <TrendChart split={!!data.daily_status} days={(data.daily_status ?? daily.map(d => ({ date: d.date, COMPLETE: 0, PARTIAL: 0, NO_EVIDENCE: 0, FAILED: 0, OTHER: d.runs }))).slice(-range)} />
              </section>
            </div>
            {data.by_condition && data.heatmap && <div className="ov-grid">
              <section className="dz-card">
                <header><h3><Ico I={Gauge} />Tốc độ và chi phí theo cách trả lời</h3><small className="is-muted">bong bóng lớn = nhiều lượt</small></header>
                <Bubbles rows={data.by_condition} />
              </section>
              <section className="dz-card">
                <header><h3><Ico I={Clock3} />Giờ cao điểm</h3><small className="is-muted">theo giờ máy chủ</small></header>
                <Heatmap grid={data.heatmap} />
              </section>
            </div>}
          </> : <EmptyState Icon={BarChart3} title="Chưa có lượt hỏi nào" text="Đặt câu hỏi ở Không gian làm việc; số liệu sẽ hiện ở đây." />}

          {data.runs > 0 && <div className="ov-grid">
            <section className="dz-card">
              <header><h3><Ico I={FileText} />Tài liệu được trích dẫn nhiều nhất</h3><small className="is-muted">{data.cite_window} lượt gần nhất</small></header>
              {data.top_documents.length === 0 ? <p className="is-muted">Chưa có trích dẫn.</p> : <TopDocs docs={data.top_documents} />}
              <h4 className="ov-sub"><FileQuestion size={14} /> Tài liệu chưa được dùng</h4>
              {data.unused_documents.length === 0 ? <p className="is-muted">Mọi tài liệu đều đã được trích dẫn ít nhất một lần.</p> :
                <div className="ov-chips is-muted-chips">{data.unused_documents.slice(0, 10).map(d => <span key={d.source_id} title={d.source_name}>{docName(d.source_name)}</span>)}{data.unused_documents.length > 10 && <span>+{data.unused_documents.length - 10}</span>}</div>}
            </section>
            <section className="dz-card">
              <header><h3><Ico I={MessageCircleQuestion} />Chủ đề được hỏi nhiều</h3><small className="is-muted">{data.window_days} ngày qua so với {data.window_days} ngày trước</small></header>
              {data.topics.length === 0 ? <p className="is-muted">Chưa có câu hỏi nào trong {data.window_days} ngày qua.</p> : <Topics topics={data.topics} days={data.window_days} />}
              <p className="tl-note">Cụm từ trong câu hỏi, tách theo từ ghép có trong kho tài liệu; mỗi câu hỏi tính một lần cho mỗi cụm.</p>
            </section>
          </div>}

          <div className="ov-grid">
            <section className="dz-card">
              <header><h3><Ico I={Cpu} />Tình trạng hệ thống</h3></header>
              <ul className="ov-sys">
                <li><span>Mô hình ngôn ngữ</span><b>{health?.ollama_model || 'Chưa rõ'}</b><em className={health?.ollama_status === 'CONNECTED' ? 'is-ok' : 'is-bad'}>{health?.ollama_status === 'CONNECTED' ? 'Đang chạy' : 'Chưa kết nối'}</em></li>
                <li><span>Cơ sở dữ liệu</span><b>{health?.database_type || 'Chưa rõ'}</b><em className={health ? 'is-ok' : ''}>{health ? 'Đang chạy' : '—'}</em></li>
                <li><span>Chỉ mục vector</span><b>Qdrant, nhúng trong backend</b><em /></li>
                <li><span>Kho của bạn</span><b>{data.sources} tài liệu · {data.chunks.toLocaleString('vi-VN')} đoạn</b><em /></li>
              </ul>
            </section>
            <section className="dz-card">
              <header><h3><Ico I={Save} />Báo cáo đã lưu</h3><small className="is-muted">{Object.values(data.reports).reduce((a, b) => a + b, 0)} báo cáo</small></header>
              {Object.keys(data.reports).length === 0 ? <p className="is-muted">Chưa lưu báo cáo nào. Các công cụ phân tích đều có nút Lưu báo cáo.</p> :
                <div className="ov-chips">{Object.entries(data.reports).sort((a, b) => b[1] - a[1]).map(([k, n]) => <span key={k}>{REPORT[k] ?? k}<b>{n}</b></span>)}</div>}
            </section>
          </div>

          <ActivityLog />
        </>}
      </div>
    </main>
  );
};

// Trang chỉ vẽ lại khi các trường sức khỏe nó hiển thị thay đổi (App làm mới sức khỏe mỗi 15 giây với object mới).
export const OverviewView = React.memo(OverviewViewImpl, (a, b) =>
  a.userName === b.userName && a.actions === b.actions && a.health?.ollama_status === b.health?.ollama_status && a.health?.ollama_model === b.health?.ollama_model && a.health?.database_type === b.health?.database_type);

/** Thẻ chỉ số: nhãn kèm biểu tượng, số lớn, huy hiệu ngữ cảnh; vòng tỉ lệ (nếu có) ở góc phải. */
function Kpi({ I, label, value, unit, ctx, ring, extra }: { I: LucideIcon; label: string; value: React.ReactNode; unit?: string; ctx: string; ring?: { value: number | null; color: string }; extra?: React.ReactNode }) {
  return (
    <div className={`ov-kpi${ring ? ' has-ring' : ''}`}>
      <span className="ov-kpi-l"><Ico I={I} />{label}</span>
      <b>{value}{unit && <small className="ov-unit"> {unit}</small>}</b>
      <em className="ov-badge">{ctx}</em>
      {extra}
      {ring && <MiniRing value={ring.value} color={ring.color} label={label} />}
    </div>
  );
}

// ---------------- Nhật ký hoạt động có phân trang và lọc
function ActivityLog() {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [res, setRes] = useState<{ rows: ActivityRow[]; total: number; pages: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    setBusy(true);
    const t = window.setTimeout(() => {
      getActivityPage(page, PAGE, q)
        // backend cũ chưa có /activity/page: lấy danh sách cũ rồi lọc, chia trang ngay trên trình duyệt
        .catch(async () => {
          const needle = q.trim().toLowerCase();
          const all = (await getActivity(500)).filter(r => !needle || `${r.action} ${r.target}`.toLowerCase().includes(needle));
          return { rows: all.slice((page - 1) * PAGE, page * PAGE), total: all.length, page, size: PAGE, pages: Math.max(1, Math.ceil(all.length / PAGE)) };
        })
        .then(r => { if (live) { setRes(r); setError(''); } }).catch(e => live && setError(e.message)).finally(() => live && setBusy(false));
    }, q ? 250 : 0);
    return () => { live = false; window.clearTimeout(t); };
  }, [page, q]);
  const exportAll = async () => {
    const all = await getActivity(5000);
    download('nhat-ky-hoat-dong.csv', '﻿' + ['Thời điểm,Thao tác,Đối tượng,Kết quả', ...all.map(r => [new Date(r.created_at).toLocaleString('vi-VN'), r.action, r.target, r.status < 400 ? 'Thành công' : `Lỗi ${r.status}`].map(csvCell).join(','))].join('\n'), 'text/csv;charset=utf-8');
  };
  const pages = res?.pages ?? 1;
  return (
    <section className="dz-card">
      <header><h3><Ico I={Activity} />Nhật ký hoạt động</h3>
        <span className="ov-logtools">
          <label className="ua-search"><Search size={14} aria-hidden="true" /><input value={q} onChange={e => { setQ(e.target.value); setPage(1); }} placeholder="Lọc theo thao tác, đối tượng" aria-label="Lọc nhật ký" /></label>
          {!!res?.total && <button className="btn btn-ghost is-sm" onClick={exportAll}><Download size={14} />Tải (.csv)</button>}
        </span>
      </header>
      {error && <p className="note is-error">{error}</p>}
      {res && res.total === 0 ? <p className="is-muted">{q ? 'Không có thao tác nào khớp.' : 'Chưa có thao tác nào được ghi. Nhật ký ghi việc nạp/xóa tài liệu, đặt câu hỏi, chạy công cụ phân tích và lưu báo cáo (không ghi nội dung câu hỏi).'}</p> :
        <div className={`tbl tv-table ov-log${busy ? ' is-busy' : ''}`}><table><thead><tr><th>Thời điểm</th><th>Thao tác</th><th>Đối tượng</th><th>Kết quả</th></tr></thead><tbody>
          {(res?.rows ?? []).map((r, i) => { const A = actionIcon(r.action), when = new Date(r.created_at);
            return <tr key={`${r.created_at}-${i}`}><td className="ov-when"><b>{tfmt.format(when)}</b><small>{dfmt.format(when)}</small></td>
              <td><span className="ov-act"><span className="ov-ico is-sm" aria-hidden="true"><A size={13} /></span>{r.action}</span></td><td className="ov-target">{r.target || '—'}</td>
              <td><span className={`ov-dot ${r.status < 400 ? 'is-ok' : 'is-bad'}`}>{r.status < 400 ? 'Thành công' : `Lỗi ${r.status}`}</span></td></tr>; })}
        </tbody></table></div>}
      {res && res.total > 0 && <nav className="ov-pager" aria-label="Phân trang nhật ký">
        <span className="is-muted">{((page - 1) * PAGE + 1).toLocaleString('vi-VN')}–{Math.min(page * PAGE, res.total).toLocaleString('vi-VN')} / {res.total.toLocaleString('vi-VN')} thao tác</span>
        <span className="ov-pages">
          <button className="icon-btn is-sm" disabled={page <= 1 || busy} onClick={() => setPage(page - 1)} aria-label="Trang trước"><ChevronLeft size={15} /></button>
          {pageList(page, pages).map((p, i) => p === 0 ? <span key={`g${i}`} className="ov-gap">…</span> :
            <button key={p} className={`ov-pg${p === page ? ' is-on' : ''}`} aria-current={p === page ? 'page' : undefined} onClick={() => setPage(p)} disabled={busy}>{p}</button>)}
          <button className="icon-btn is-sm" disabled={page >= pages || busy} onClick={() => setPage(page + 1)} aria-label="Trang sau"><ChevronRight size={15} /></button>
        </span>
      </nav>}
    </section>
  );
}

/** Dãy số trang gọn: 1 … 4 5 6 … 20 (0 = dấu ba chấm). */
function pageList(cur: number, total: number): number[] {
  const want = new Set([1, total, cur - 1, cur, cur + 1].filter(p => p >= 1 && p <= total));
  const sorted = [...want].sort((a, b) => a - b);
  return sorted.flatMap((p, i) => (i && p - sorted[i - 1] > 1 ? [0, p] : [p]));
}

// ---------------- Biểu đồ
/** Vòng tỉ lệ nhỏ ở góc thẻ chỉ số (con số đã ghi ở thẻ); null = chưa có dữ liệu. */
function MiniRing({ value, color, label }: { value: number | null; color: string; label: string }) {
  const r = 17, c = 2 * Math.PI * r;
  return (
    <svg className="ov-mring" viewBox="0 0 44 44" role="img" aria-label={`${label}: ${value == null ? 'chưa có' : `${value}%`}`}>
      <circle cx="22" cy="22" r={r} fill="none" stroke="var(--ring-track,#e8edf3)" strokeWidth="5" />
      {value != null && <circle cx="22" cy="22" r={r} fill="none" stroke={color} strokeWidth="5" strokeLinecap="round"
        strokeDasharray={`${(value / 100) * c} ${c}`} transform="rotate(-90 22 22)" />}
    </svg>
  );
}

/** Vành khuyên tỉ lệ trạng thái, có khe hở 2px giữa các phần và chú giải đầy đủ (nhãn + số + %). */
function Donut({ parts, total, foot }: { parts: { key: string; label: string; color: string; value: number }[]; total: number; foot?: React.ReactNode }) {
  const [hover, setHover] = useState<string | null>(null);
  const R = 62, W = 18, C = 2 * Math.PI * R, gap = total ? 2 : 0;
  let acc = 0;
  const shown = parts.filter(p => p.value > 0);
  const active = parts.find(p => p.key === hover);
  return (
    <div className="ov-donut">
      <svg viewBox="0 0 160 160" role="img" aria-label={parts.map(p => `${p.label} ${p.value}`).join(', ')}>
        <circle cx="80" cy="80" r={R} fill="none" stroke="var(--ring-track,#e8edf3)" strokeWidth={W} />
        {shown.map(p => {
          const len = (p.value / total) * C;
          const seg = <circle key={p.key} cx="80" cy="80" r={R} fill="none" stroke={p.color} strokeWidth={hover === p.key ? W + 4 : W}
            strokeDasharray={`${Math.max(0, len - (shown.length > 1 ? gap : 0))} ${C}`} strokeDashoffset={-acc} transform="rotate(-90 80 80)"
            onMouseEnter={() => setHover(p.key)} onMouseLeave={() => setHover(null)} style={{ cursor: 'default', transition: 'stroke-width .15s' }}>
            <title>{`${p.label}: ${p.value} (${Math.round((p.value / total) * 100)}%)`}</title></circle>;
          acc += len;
          return seg;
        })}
        <text x="80" y="76" textAnchor="middle" className="ov-donut-n">{active ? active.value.toLocaleString('vi-VN') : total.toLocaleString('vi-VN')}</text>
        <text x="80" y="96" textAnchor="middle" className="ov-donut-l">{active ? active.label : 'lượt'}</text>
      </svg>
      <ul className="ov-legend">
        {parts.map(p => <li key={p.key} onMouseEnter={() => setHover(p.key)} onMouseLeave={() => setHover(null)} className={hover === p.key ? 'is-on' : ''}>
          <i style={{ background: p.color }} /><span>{p.label}</span><b>{p.value.toLocaleString('vi-VN')}</b><em>{total ? Math.round((p.value / total) * 100) : 0}%</em></li>)}
        {foot && <li className="ov-legend-foot">{foot}</li>}
      </ul>
    </div>
  );
}

/** Đường cong lượt hỏi theo ngày: vùng tô gradient, làm nổi một ngày (mặc định ngày cao nhất) bằng chấm, bóng số và đường gióng.
 *  Rê chuột hoặc dùng phím mũi tên (khi biểu đồ có tiêu điểm) để xem từng ngày; bảng nổi tách số lượt theo kết quả. */
function TrendChart({ days, split }: { days: NonNullable<Overview['daily_status']>; split: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);
  const gid = React.useId().replace(/:/g, '');
  const W = 600, H = 220, L = 32, B = 26, T = 36, R = 14;
  const totals = days.map(d => STATUS.reduce((n, x) => n + d[x.key], 0) + d.OTHER);
  const peak = totals.reduce((best, v, i) => (v > totals[best] ? i : best), 0);
  const nice = Math.max(5, Math.ceil(Math.max(1, ...totals) / 5) * 5);
  const x = (i: number) => L + (i / Math.max(1, days.length - 1)) * (W - L - R);
  const y = (v: number) => T + (1 - v / nice) * (H - T - B);
  const line = useMemo(() => smoothPath(totals.map((v, i) => [x(i), y(v)])), [days]); // eslint-disable-line react-hooks/exhaustive-deps
  const hi = hover ?? peak;
  const onMove = (e: React.PointerEvent) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const px = ((e.clientX - r.left) / r.width) * W;
    setHover(Math.max(0, Math.min(days.length - 1, Math.round(((px - L) / (W - L - R)) * (days.length - 1)))));
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    setHover(h => { const cur = h ?? peak; return e.key === 'Home' ? 0 : e.key === 'End' ? days.length - 1 : Math.max(0, Math.min(days.length - 1, cur + (e.key === 'ArrowRight' ? 1 : -1))); });
  };
  const px = x(hi), py = y(totals[hi]), label = `${totals[hi].toLocaleString('vi-VN')} lượt`;
  const pillW = label.length * 6.6 + 18;
  const d = days[hi];
  const step = days.length > 8 ? 2 : 1;
  return (
    <div className="ov-trend">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} tabIndex={0} role="img" className="ov-trend-svg"
        aria-label={`Lượt hỏi ${days.length} ngày: ${days.map((dd, i) => `${dayLabel(dd.date)} ${totals[i]}`).join(', ')}. Cao nhất ${dayLabel(days[peak].date)}: ${totals[peak]} lượt.`}
        onPointerMove={onMove} onPointerLeave={() => setHover(null)} onKeyDown={onKey} onBlur={() => setHover(null)}>
        <defs>
          <linearGradient id={`g${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity=".28" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map(f => <g key={f}><line x1={L} x2={W - R} y1={y(nice * f)} y2={y(nice * f)} className="ov-grid-line" strokeDasharray={f ? '3 4' : undefined} />
          <text x={L - 8} y={y(nice * f) + 4} textAnchor="end" className="ov-axis">{Math.round(nice * f)}</text></g>)}
        <path d={`${line}L${x(days.length - 1)} ${y(0)}L${x(0)} ${y(0)}Z`} fill={`url(#g${gid})`} />
        <path d={line} fill="none" className="ov-trend-line" />
        {days.map((dd, i) => i % step === (days.length - 1) % step && <text key={dd.date} x={x(i)} y={H - 6} textAnchor="middle" className={`ov-axis${i === hi ? ' is-on' : ''}`}>{dayLabel(dd.date)}</text>)}
        <line x1={px} x2={px} y1={py + 6} y2={y(0)} className="ov-guide" />
        <circle cx={px} cy={py} r="5.5" className="ov-trend-dot" />
        <g transform={`translate(${Math.min(Math.max(px - pillW / 2, L), W - R - pillW)} ${Math.max(py - 32, 2)})`}>
          <rect width={pillW} height="22" rx="11" className="ov-pill" />
          <text x={pillW / 2} y="15" textAnchor="middle" className="ov-pill-t">{label}</text>
        </g>
      </svg>
      {hover != null && split && <div className={`ov-tip${hover > days.length / 2 ? ' is-left' : ''}`} style={{ left: `${(px / W) * 100}%` }}>
        <b>{dayLabel(d.date)} · {totals[hi]} lượt</b>
        {STATUS.map(st => <span key={st.key}><i style={{ background: st.color }} />{st.label}<em>{d[st.key]}</em></span>)}
      </div>}
      <p className="ov-trend-foot is-muted">{hover == null ? <>Cao nhất <b>{dayLabel(days[peak].date)}</b> với {totals[peak].toLocaleString('vi-VN')} lượt · tổng {totals.reduce((a2, b2) => a2 + b2, 0).toLocaleString('vi-VN')} lượt trong {days.length} ngày</> : <>Đang xem <b>{dayLabel(d.date)}</b>{split ? ' · rê chuột ra ngoài để về ngày cao nhất' : ''}</>}</p>
    </div>
  );
}

/** Bong bóng: trục ngang thời gian trung bình, trục dọc token trung bình, cỡ = số lượt, có nhãn tên trực tiếp. */
function Bubbles({ rows }: { rows: NonNullable<Overview['by_condition']> }) {
  const pts = rows.filter(r => r.latency_avg_ms != null && r.tokens_avg != null);
  const missing = rows.filter(r => r.latency_avg_ms == null || r.tokens_avg == null);
  if (!pts.length) return <p className="is-muted">Chưa có lượt nào đo được thời gian và token.</p>;
  const W = 520, H = 250, L = 46, B = 42, T = 26;
  const maxX = Math.max(...pts.map(p => p.latency_avg_ms!)) * 1.15, maxY = Math.max(...pts.map(p => p.tokens_avg!)) * 1.15;
  const maxRuns = Math.max(...pts.map(p => p.runs));
  const x = (v: number) => L + (v / maxX) * (W - L - 16);
  const y = (v: number) => T + (1 - v / maxY) * (H - T - B);
  const r = (n: number) => 8 + Math.sqrt(n / maxRuns) * 18;
  // nhãn tên đặt bên phải bong bóng; nhãn nào đè nhãn trước thì đẩy xuống và nối bằng đường mảnh
  const labels: { condition: string; x: number; y: number; ax: number; ay: number; moved: boolean }[] = [];
  for (const p of [...pts].sort((a, b) => y(a.tokens_avg!) - y(b.tokens_avg!))) {
    const ax = x(p.latency_avg_ms!) + r(p.runs), ay = y(p.tokens_avg!);
    let ly = ay + 4;
    for (const o of labels) if (Math.abs(o.x - (ax + 4)) < 46 && Math.abs(o.y - ly) < 14) ly = o.y + 14;
    labels.push({ condition: p.condition, x: Math.min(ax + 4, W - 40), y: ly, ax, ay, moved: ly !== ay + 4 });
  }
  return (
    <div className="ov-bubbles">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={pts.map(p => `${COND[p.condition] ?? p.condition}: ${fmtSeconds(p.latency_avg_ms!)} giây, ${p.tokens_avg} token, ${p.runs} lượt`).join('; ')}>
        {[0, 0.5, 1].map(f => <g key={f}>
          <line x1={L} x2={W - 16} y1={y(maxY * f)} y2={y(maxY * f)} className="ov-grid-line" />
          <text x={L - 6} y={y(maxY * f) + 4} textAnchor="end" className="ov-axis">{Math.round((maxY * f) / 100) / 10}k</text>
          <text x={x(maxX * f)} y={H - B + 16} textAnchor={f === 1 ? 'end' : 'middle'} className="ov-axis">{fmtSeconds(maxX * f)}s</text>
        </g>)}
        {[...pts].sort((a, b) => b.runs - a.runs).map(p => <circle key={p.condition} cx={x(p.latency_avg_ms!)} cy={y(p.tokens_avg!)} r={r(p.runs)} fill={COND_COLOR[p.condition] ?? '#7b8ba1'} fillOpacity={0.78} stroke="var(--surface,#fff)" strokeWidth="2">
          <title>{`${COND[p.condition] ?? p.condition}: ${p.runs} lượt · ${fmtSeconds(p.latency_avg_ms!)} s · ${p.tokens_avg!.toLocaleString('vi-VN')} token · ${Math.round((p.complete / p.runs) * 100)}% đủ bằng chứng`}</title>
        </circle>)}
        {labels.map(l => <g key={l.condition}>
          {l.moved && <line x1={l.ax} y1={l.ay} x2={l.x - 2} y2={l.y - 4} className="ov-leader" />}
          <text x={l.x} y={l.y} className="ov-blabel">{l.condition}</text>
        </g>)}
        <text x={W - 16} y={H - 4} textAnchor="end" className="ov-axis is-title">thời gian trung bình →</text>
        <text x={L} y={12} className="ov-axis is-title">↑ token trung bình</text>
      </svg>
      <ul className="ov-legend is-row">{pts.map(p => <li key={p.condition}><i style={{ background: COND_COLOR[p.condition] ?? '#7b8ba1' }} /><span>{COND[p.condition] ?? p.condition}</span><em>{p.runs}</em></li>)}</ul>
      {missing.length > 0 && <p className="tl-note">Chưa đo: {missing.map(m => m.condition).join(', ')}.</p>}
    </div>
  );
}

/** Bản đồ nhiệt thứ x giờ (một sắc xanh, nhạt = ít, đậm = nhiều); ô 0 để màu nền nhạt nhất. */
function Heatmap({ grid }: { grid: number[][] }) {
  const max = Math.max(1, ...grid.flat());
  const level = (v: number) => (v ? Math.min(HEAT.length - 1, 1 + Math.floor((v / max) * (HEAT.length - 1.01))) : 0);
  const peak = grid.flatMap((row, d) => row.map((v, h) => ({ v, d, h }))).sort((a, b) => b.v - a.v)[0];
  return (
    <div className="ov-heat">
      <div className="ov-heat-grid" role="img" aria-label={peak?.v ? `Cao điểm: ${WEEKDAY[peak.d]} lúc ${peak.h} giờ, ${peak.v} lượt` : 'Chưa có lượt nào'}>
        <span />
        {Array.from({ length: 24 }, (_, h) => <span key={h} className="ov-heat-h">{h % 3 === 0 ? h : ''}</span>)}
        {grid.map((row, d) => <React.Fragment key={d}>
          <span className="ov-heat-d">{WEEKDAY[d]}</span>
          {row.map((v, h) => <i key={h} className={v ? undefined : 'is-zero'} style={v ? { background: HEAT[level(v)] } : undefined} title={`${WEEKDAY[d]}, ${h}:00–${h + 1}:00: ${v} lượt`} />)}
        </React.Fragment>)}
      </div>
      <div className="ov-heat-foot">
        <span className="is-muted">{peak?.v ? <>Cao điểm: <b>{WEEKDAY[peak.d]}, {peak.h}–{peak.h + 1} giờ</b> ({peak.v} lượt)</> : 'Chưa có lượt nào.'}</span>
        <span className="ov-heat-scale" aria-hidden="true">ít{HEAT.map(c => <i key={c} style={{ background: c }} />)}nhiều</span>
      </div>
    </div>
  );
}

/** Tài liệu trích dẫn nhiều nhất: thanh ngang có thứ hạng (giữ một biểu đồ thanh vì so sánh độ lớn theo tên). */
function TopDocs({ docs }: { docs: Overview['top_documents'] }) {
  const max = Math.max(1, ...docs.map(d => d.citations));
  return <ol className="ov-rank">{docs.map((d, i) => <li key={d.source_id} title={d.source_name}>
    <em>{i + 1}</em><span>{docName(d.source_name)}</span><i><u style={{ width: `${(d.citations / max) * 100}%` }} /></i><b>{d.citations}</b></li>)}</ol>;
}

/** Ô chủ đề: diện tích theo số lượt hỏi, đậm nhạt theo số lượt, kèm xu hướng so với kỳ trước. */
function Topics({ topics, days }: { topics: Overview['topics']; days: number }) {
  const max = Math.max(1, ...topics.map(t => t.count));
  return <div className="ov-tiles">{topics.map(t => {
    const up = t.count > t.previous, down = t.count < t.previous;
    const top = t.count === max;
    // ô nhiều nhất dùng màu nhấn; các ô khác pastel nhạt (đậm hơn một bậc nếu trên 60% ô lớn nhất), chữ tối
    return <div key={t.term} className={`ov-tile${top ? ' is-dark' : ''}`} style={{ flexGrow: t.count, background: top ? 'var(--accent)' : HEAT[t.count / max > 0.6 ? 2 : 1] }}
      title={`${t.term}: ${t.count} lượt (${t.previous} lượt ở ${days} ngày trước)`}>
      <span>{t.term}</span><b>{t.count}</b>
      <em className={up ? 'is-up' : down ? 'is-down' : ''}>{up ? <TrendingUp size={12} /> : down ? <TrendingDown size={12} /> : null}{t.previous === 0 ? 'mới' : `${t.count - t.previous > 0 ? '+' : ''}${t.count - t.previous}`}</em>
    </div>;
  })}</div>;
}

// Đường nhỏ 14 ngày trong ô dẫn: số lượt hỏi mỗi ngày.
function Spark({ days }: { days: { date: string; runs: number }[] }) {
  if (!days?.length) return null;
  const w = 120, h = 34, max = Math.max(1, ...days.map(d => d.runs));
  const pts = days.map((d, i) => [(i / (days.length - 1)) * w, h - 3 - (d.runs / max) * (h - 6)]);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join('');
  return <svg className="ov-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="Lượt hỏi 14 ngày gần nhất">
    <path d={`${line}L${w} ${h}L0 ${h}Z`} fill="rgba(22,194,192,.18)" />
    <path d={line} fill="none" stroke="#5fe0d8" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
  </svg>;
}
