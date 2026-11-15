// Giám sát hệ thống: số đo thật của máy chủ (CPU, RAM, ổ đĩa), Ollama, PostgreSQL, Qdrant; tự làm mới mỗi 10 giây khi trang đang mở.
// Đường CPU là các lần đo thật trong phiên đang xem (không vẽ lịch sử giả). Đo không được thì hiện "Chưa đo".
import React, { useEffect, useRef, useState } from 'react';
import { Activity, AlertTriangle, Bot, CheckCircle2, Cpu, Database, HardDrive, Layers, MemoryStick, Pause, Play, RefreshCw, Boxes, FileText, LogIn, MessagesSquare, PlayCircle, Server, ServerCrash, Users, XCircle } from 'lucide-react';
import { AdminSystem, AuditRow, getAdminAudit, getAdminSystem } from '../../services/api';
import { useProfileMotion } from '../profile/ProfileParts';

export const fmtBytes = (b: number | null | undefined) => {
  if (b == null) return 'Chưa đo';
  const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; let v = b;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toLocaleString('vi-VN', { maximumFractionDigits: v >= 100 || i === 0 ? 0 : 1 })} ${u[i]}`;
};
const fmtUptime = (s?: number) => {
  if (s == null) return 'Chưa đo';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} ngày ${h} giờ` : h ? `${h} giờ ${m} phút` : `${m} phút`;
};
const num = (v: number | null | undefined) => (v == null ? '—' : v.toLocaleString('vi-VN'));
const level = (p?: number | null) => (p == null ? 'none' : p >= 90 ? 'bad' : p >= 70 ? 'warn' : 'ok');
/** Máy chủ đang chạy bản cũ (chưa có API quản trị) thì gọi /api/admin/system trả 404. */
export const isOldBackend = (msg: string | null) => !!msg && /404|not found/i.test(msg);

export function OldBackendNote() {
  return (
    <section className="ap-card ap-old" role="alert">
      <span className="ap-ico is-warn"><ServerCrash size={20} /></span>
      <div><h2>Máy chủ đang chạy phiên bản cũ</h2>
        <p>Backend ở cổng 8000 được khởi động trước khi có Bảng điều khiển quản trị, nên chưa có số đo. Khởi động lại Backend là xong:
          trong VS Code mở <b>Terminal → Terminate Task → Backend</b>, rồi nhấn <b>Ctrl+Shift+B</b> (hoặc chạy <b>TAT_ORCHESTRIQ.cmd</b> rồi <b>MO_ORCHESTRIQ.cmd</b>).</p></div>
    </section>
  );
}

function MiniRing({ value }: { value: number | null | undefined }) {
  const R = 22, C = 2 * Math.PI * R; const v = value == null ? null : Math.max(0, Math.min(100, value));
  return (
    <span className={`ap-mring is-${level(v)}`} aria-hidden="true">
      <svg viewBox="0 0 56 56"><circle className="t" cx="28" cy="28" r={R} />{v != null && <circle className="b" cx="28" cy="28" r={R} strokeDasharray={C} strokeDashoffset={C * (1 - v / 100)} />}</svg>
      <b>{v == null ? '—' : `${Math.round(v)}%`}</b>
    </span>
  );
}

function Spark({ data }: { data: number[] }) {
  if (data.length < 2) return <span className="ap-spark is-empty">Đang thu số đo…</span>;
  const w = 240, h = 48;
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, h - (v / 100) * (h - 4) - 2]);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  return (
    <svg className="ap-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id="ap-spark-g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity=".32" /><stop offset="100%" stopColor="var(--accent)" stopOpacity="0" /></linearGradient></defs>
      <path d={`${d} L${w} ${h} L0 ${h} Z`} fill="url(#ap-spark-g)" /><path className="l" d={d} />
    </svg>
  );
}

function Kpi({ Icon, label, value, sub, pct, viz }: { Icon: React.ComponentType<{ size?: number }>; label: string; value: React.ReactNode; sub: React.ReactNode; pct?: number | null; viz?: React.ReactNode }) {
  return (
    <section className="ap-card ap-kpi ap-anim">
      <header><span className="ap-ico"><Icon size={17} /></span><span className="ap-kpi-l">{label}</span>
        {pct != null && <span className={`ap-badge is-${level(pct)}`}>{Math.round(pct)}%</span>}</header>
      <b className="ap-kpi-v">{value}</b>
      <div className="ap-kpi-viz">{viz}</div>
      <small>{sub}</small>
    </section>
  );
}

const Bar = ({ pct }: { pct?: number | null }) => (
  <span className={`ap-bar is-${level(pct)}`} aria-hidden="true"><i style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%` }} /></span>
);

function Svc({ Icon, name, sub, ok, state, children }: { Icon: React.ComponentType<{ size?: number }>; name: string; sub: string; ok: boolean | null; state: string; children: React.ReactNode }) {
  return (
    <section className={`ap-card ap-svc ap-anim is-${ok == null ? 'warn' : ok ? 'ok' : 'bad'}`}>
      <header><span className="ap-tile"><Icon size={20} /></span><span className="ap-svc-n"><b>{name}</b><small>{sub}</small></span>
        <span className="ap-pill">{ok == null ? <AlertTriangle size={13} /> : ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />}{state}</span></header>
      <dl>{children}</dl>
    </section>
  );
}
const TILE_ICON = [Users, LogIn, FileText, Boxes, MessagesSquare, PlayCircle];
const Row = ({ k, v }: { k: string; v: React.ReactNode }) => <div><dt>{k}</dt><dd>{v}</dd></div>;

export function SystemHealth({ onOpenAudit }: { onOpenAudit: () => void }) {
  const [sys, setSys] = useState<AdminSystem | null>(null);
  const [errs, setErrs] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(true);
  const [cpu, setCpu] = useState<number[]>([]);
  const alive = useRef(true);
  const root = useRef<HTMLDivElement>(null);

  const load = async () => {
    setBusy(true);
    try {
      const s = await getAdminSystem(); if (!alive.current) return;
      setSys(s); setError(null);
      if (s.host.cpu_percent != null) setCpu(c => [...c.slice(-39), s.host.cpu_percent!]);
      getAdminAudit(1, 5, '', true).then(r => alive.current && setErrs(r.rows)).catch(() => undefined);
    } catch (e: any) { if (alive.current) setError(String(e?.message || e)); } finally { if (alive.current) setBusy(false); }
  };
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (!auto) return;
    const t = window.setInterval(() => { if (!document.hidden) void load(); }, 10000);
    return () => window.clearInterval(t);
  }, [auto]);

  useProfileMotion(root, sys ? 'ready' : 'wait', '.ap-anim');
  const h = sys?.host, o = sys?.ollama, pg = sys?.postgres, qd = sys?.qdrant;
  const ollamaOk = o ? (o.reachable ? !!o.chat_model_ready : false) : null;
  const down = sys ? ([['PostgreSQL', pg!.reachable], ['Qdrant', qd!.exists], ['Ollama', ollamaOk]] as [string, boolean | null][]).filter(([, ok]) => !ok).map(([n]) => n) : [];

  return (
    <div className="ap-page" ref={root}>
      <section className={`ap-hero ap-anim${sys && down.length ? ' is-warn' : ''}`}>
        <div className="ap-hero-l">
          <p className="ap-hero-k">Bảng điều khiển quản trị · Giám sát hệ thống</p>
          <h1>{!sys ? (error ? 'Chưa đọc được số đo' : 'Đang đọc số đo…') : down.length ? `${down.length} dịch vụ cần chú ý` : 'Hệ thống đang ổn định'}</h1>
          <p>{sys ? <>Số đo thật lúc <b>{new Date(sys.measured_at).toLocaleTimeString('vi-VN')}</b> · {auto ? 'tự làm mới mỗi 10 giây' : 'đã tạm dừng làm mới'}</> : 'Số đo thật của máy chủ đang chạy OrchestrIQ.'}</p>
          <div className="ap-hero-act">
            <button className="ap-hbtn is-solid" onClick={() => void load()} disabled={busy}><RefreshCw size={15} className={busy ? 'is-spin' : ''} />Làm mới</button>
            <button className="ap-hbtn" onClick={() => setAuto(v => !v)} aria-pressed={auto}>{auto ? <Pause size={15} /> : <Play size={15} />}{auto ? 'Tạm dừng' : 'Tự làm mới'}</button>
          </div>
        </div>
        {sys && <ul className="ap-hero-svcs" aria-label="Trạng thái dịch vụ">
          {([['Máy chủ API', true, 'Đang chạy'], ['PostgreSQL', pg!.reachable, pg!.reachable ? 'Đang chạy' : 'Không kết nối'], ['Qdrant', qd!.exists, qd!.exists ? 'Có dữ liệu' : 'Chưa tạo'],
            ['Ollama', ollamaOk, !o!.reachable ? 'Không kết nối' : o!.chat_model_ready ? 'Sẵn sàng' : 'Thiếu mô hình']] as [string, boolean | null, string][]).map(([n, ok, st]) => (
            <li key={n} className={ok ? 'is-ok' : 'is-bad'}><i /><b>{n}</b><span>{st}</span></li>))}
        </ul>}
      </section>

      {isOldBackend(error) ? <OldBackendNote /> : error && <p className="ap-note is-bad" role="alert"><XCircle size={15} />Không đọc được số đo: {error}</p>}

      {!isOldBackend(error) && <>
        <div className="ap-kpis">
          <Kpi Icon={Cpu} label="CPU toàn máy" pct={h?.cpu_percent} value={h?.cpu_percent == null ? '—' : <>{Math.round(h.cpu_percent)}<small>%</small></>}
            viz={<Spark data={cpu} />} sub={`${h?.cpu_count ?? '—'} luồng · ${cpu.length} lần đo trong phiên này`} />
          <Kpi Icon={MemoryStick} label="Bộ nhớ RAM" pct={h?.ram_percent} value={fmtBytes(h?.ram_used_bytes)} viz={<Bar pct={h?.ram_percent} />} sub={`đang dùng, trên ${fmtBytes(h?.ram_total_bytes)}`} />
          <Kpi Icon={HardDrive} label="Ổ đĩa dữ liệu" pct={h?.disk?.percent} value={<>{fmtBytes(h?.disk?.free_bytes)} <em>trống</em></>} viz={<Bar pct={h?.disk?.percent} />} sub={h?.disk ? `trên ${fmtBytes(h.disk.total_bytes)}` : 'Chưa đo'} />
          <Kpi Icon={Activity} label="Máy chủ API" value={fmtUptime(h?.backend_uptime_s)}
            viz={<span className="ap-live"><i />Đang phục vụ{h?.backend_uptime_s != null ? ` từ ${new Date(Date.now() - h.backend_uptime_s * 1000).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}` : ''}</span>}
            sub={`RAM tiến trình ${fmtBytes(h?.backend_rss_bytes)}`} />
        </div>

        {sys && <div className="ap-svcs">
          <Svc Icon={Bot} name="Ollama" sub="Mô hình cục bộ" ok={ollamaOk} state={!o!.reachable ? 'Không kết nối' : o!.chat_model_ready ? 'Sẵn sàng' : 'Thiếu mô hình'}>
            <Row k="Mô hình trả lời" v={<>{o!.chat_model}{o!.reachable && <i className={o!.chat_model_ready ? 'ap-ok' : 'ap-bad'}>{o!.chat_model_ready ? 'đã tải' : 'chưa có'}</i>}</>} />
            <Row k="Mô hình nhúng" v={<>{o!.embed_model}{o!.reachable && <i className={o!.embed_model_ready ? 'ap-ok' : 'ap-bad'}>{o!.embed_model_ready ? 'đã tải' : 'chưa có'}</i>}</>} />
            <Row k="Đang nạp sẵn" v={o!.loaded == null ? 'Chưa đo' : o!.loaded.length ? o!.loaded.map(m => m.name).join(', ') : 'Chưa nạp'} />
            <Row k="RAM · GPU" v={`${o!.process_rss_mb == null ? 'Chưa đo' : fmtBytes(o!.process_rss_mb * 1048576)} · ${o!.gpu_memory_mb == null ? 'không có GPU' : fmtBytes(o!.gpu_memory_mb * 1048576)}`} />
          </Svc>
          <Svc Icon={Database} name="PostgreSQL" sub="Cơ sở dữ liệu" ok={pg!.reachable} state={pg!.reachable ? 'Đang chạy' : 'Không kết nối'}>
            <Row k="Dung lượng" v={fmtBytes(pg!.size_bytes)} />
            <Row k="Kết nối đang mở" v={num(pg!.connections)} />
            <Row k="Phiên bản" v={pg!.version?.split(' ')[0] ?? 'Chưa đo'} />
            <Row k="Lược đồ" v={pg!.alembic_version ?? '—'} />
          </Svc>
          <Svc Icon={Layers} name="Qdrant" sub="Chỉ mục vector" ok={qd!.exists} state={qd!.exists ? 'Có dữ liệu' : 'Chưa tạo'}>
            <Row k="Dung lượng trên đĩa" v={fmtBytes(qd!.size_bytes)} />
            <Row k="Bộ sưu tập" v={qd!.collections.length ? qd!.collections.join(', ') : 'Chưa có'} />
            <Row k="Chế độ" v={qd!.backend} />
          </Svc>
          <Svc Icon={Server} name="Máy chủ" sub="Môi trường chạy" ok={h?.available ?? null} state={h?.available ? 'Đang chạy' : 'Không đo được'}>
            <Row k="Hệ điều hành" v={h?.platform ?? 'Chưa đo'} />
            <Row k="Python" v={h?.python ?? '—'} />
            <Row k="Mô hình qua" v={sys.provider} />
            <Row k="Nhúng văn bản qua" v={sys.embedding_backend} />
          </Svc>
        </div>}

        {sys && <div className="ap-split">
          <section className="ap-card ap-anim">
            <header className="ap-card-head"><h2><span className="ap-ico"><Users size={16} /></span>Dữ liệu trong hệ thống</h2></header>
            <ul className="ap-tiles">{([['users', 'Tài khoản'], ['active_sessions', 'Phiên đang đăng nhập'], ['knowledge_sources', 'Tài liệu'], ['knowledge_chunks', 'Đoạn đã lập chỉ mục'], ['conversations', 'Cuộc trò chuyện'], ['runs', 'Lượt chạy']] as [string, string][])
              .map(([k, l], i) => { const I = TILE_ICON[i]; return <li key={k} className={`t${i}`}><span className="ap-tile-i"><I size={16} /></span><b>{num(pg!.counts[k])}</b><span>{l}</span></li>; })}</ul>
          </section>
          <section className="ap-card ap-anim">
            <header className="ap-card-head"><h2><span className="ap-ico is-warn"><AlertTriangle size={16} /></span>Lỗi gần đây</h2><button className="ap-link" onClick={onOpenAudit}>Mở nhật ký kiểm toán</button></header>
            {errs.length === 0 ? <p className="ap-allgood"><CheckCircle2 size={18} />Không có thao tác lỗi nào được ghi nhận gần đây.</p>
              : <ul className="ap-errs">{errs.map((e, i) => <li key={i}><span className="ap-code">{e.status}</span><span><b>{e.action}</b><small>{e.display_name || e.email || 'Không rõ'} · {new Date(e.created_at).toLocaleString('vi-VN')}</small></span></li>)}</ul>}
          </section>
        </div>}
      </>}
    </div>
  );
}
