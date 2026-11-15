// Cấu hình AI & tham số điều phối: xem (chỉ đọc) cấu hình đang chạy, mã cấu hình (config_hash) và các mô hình có trong Ollama.
// Không sửa tại đây: tham số là một phần của phương pháp nghiên cứu, đổi giữa chừng làm các lượt chạy không so sánh được.
import React, { useEffect, useState } from 'react';
import { Bot, Copy, Fingerprint, Lock, SlidersHorizontal } from 'lucide-react';
import { AdminSystem, getAdminSystem, getRuntimeConfig } from '../../services/api';
import { fmtBytes, isOldBackend, OldBackendNote } from './SystemHealth';

const GROUPS: [string, RegExp][] = [
  ['Mô hình và nhà cung cấp', /model|provider|ollama|embed|temperature|num_ctx|think/i],
  ['Truy xuất và ngữ cảnh', /top_k|retriev|chunk|context|budget|rerank|vector|qdrant|token/i],
  ['Điều phối tác tử', /plan|agent|condition|profile|task|dedup|max_|timeout|retry/i],
];

export function AiSettings() {
  const [cfg, setCfg] = useState<Record<string, any> | null>(null);
  const [sys, setSys] = useState<AdminSystem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [sysErr, setSysErr] = useState<string | null>(null);
  useEffect(() => {
    getRuntimeConfig().then(setCfg).catch(e => setError(e.message));
    getAdminSystem().then(setSys).catch(e => setSysErr(String(e?.message || e)));
  }, []);
  const entries = cfg ? Object.entries(cfg).filter(([k]) => k !== 'config_hash') : [];
  const grouped = GROUPS.map(([g, re]) => [g, entries.filter(([k]) => re.test(k))] as const);
  const used = new Set(grouped.flatMap(([, list]) => list.map(([k]) => k)));
  const rest = entries.filter(([k]) => !used.has(k));
  const show = (v: any) => (Array.isArray(v) ? v.join(', ') : typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v));

  return (
    <div className="ap-page">
      <header className="ap-head">
        <div><p className="ap-kicker">Bảng điều khiển quản trị</p><h1>Cấu hình AI & tham số điều phối</h1><p>Cấu hình đang chạy của mô hình, truy xuất và các tác tử. Mỗi lượt chạy ghi lại mã cấu hình để tái lập.</p></div>
      </header>
      {error && <p className="ap-note is-bad" role="alert">{error}</p>}
      {isOldBackend(sysErr) && <OldBackendNote />}
      <div className="ap-ai-top">
        <section className="ap-card ap-hash">
          <span className="ap-svc-ico"><Fingerprint size={18} /></span>
          <div><small>Mã cấu hình (config_hash)</small><code>{cfg?.config_hash ?? '…'}</code></div>
          {cfg?.config_hash && <button className="ap-btn" onClick={() => { void navigator.clipboard?.writeText(String(cfg.config_hash)); setCopied(true); setTimeout(() => setCopied(false), 1500); }}><Copy size={14} />{copied ? 'Đã chép' : 'Chép'}</button>}
        </section>
        <section className="ap-card ap-lock"><Lock size={18} /><p><b>Chỉ đọc tại đây.</b> Tham số thuộc phương pháp nghiên cứu (điều kiện A/B/C, ngân sách ngữ cảnh). Đổi trong tệp cấu hình môi trường rồi khởi động lại máy chủ, để mọi lượt chạy cùng đợt dùng chung một mã cấu hình.</p></section>
      </div>
      <div className="ap-cfg">
        {[...grouped, ['Khác', rest] as const].filter(([, list]) => list.length).map(([g, list]) => (
          <section key={g} className="ap-card">
            <header><h3><SlidersHorizontal size={16} />{g}</h3><small>{list.length} tham số</small></header>
            <dl className="ap-kv">{list.map(([k, v]) => <div key={k}><dt><code>{k}</code></dt><dd>{show(v)}</dd></div>)}</dl>
          </section>
        ))}
      </div>
      <section className="ap-card">
        <header><h3><Bot size={16} />Mô hình có trong Ollama</h3><small>{sys ? (sys.ollama.reachable ? `${sys.ollama.models.length} mô hình` : 'Không kết nối được Ollama') : sysErr ? 'Chưa đọc được (khởi động lại Backend)' : 'Đang đọc…'}</small></header>
        {sys?.ollama.reachable && <div className="ap-table"><table>
          <thead><tr><th>Mô hình</th><th>Họ</th><th>Tham số</th><th>Lượng tử hóa</th><th className="ap-r">Dung lượng</th><th>Vai trò</th></tr></thead>
          <tbody>{sys.ollama.models.map(m => {
            const role = m.name === sys.ollama.chat_model || m.name === `${sys.ollama.chat_model}:latest` ? 'Trả lời' : m.name.startsWith(sys.ollama.embed_model ?? '§') ? 'Nhúng văn bản' : '';
            return <tr key={m.name}><td><b>{m.name}</b></td><td>{m.family ?? '—'}</td><td>{m.parameter_size ?? '—'}</td><td>{m.quantization ?? '—'}</td><td className="ap-r">{fmtBytes(m.size_bytes)}</td>
              <td>{role ? <span className="ap-status is-ok">{role}</span> : <span className="ap-muted">Không dùng</span>}</td></tr>;
          })}</tbody>
        </table></div>}
      </section>
    </div>
  );
}
