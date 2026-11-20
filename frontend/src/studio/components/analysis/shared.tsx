// Phần dùng chung của các trang phân tích (truy vết, gói thiết kế, rà soát bảo mật, đánh giá).
import React, { useEffect, useState } from 'react';
import { getChunk, getDocuments, listReports, SavedReport } from '../../services/api';
import { Check, FileText, FolderOpen } from 'lucide-react';
import { StudioModal } from '../StudioModal';

export type Doc = { id?: number | string; source_file: string; chunks_count?: number };
export const docId = (d: Doc) => String(d.id ?? '');
export const baseName = (name: string) => name.replace(/\.[^.]+$/, '') || 'tai-lieu';
export const chunkLabel = (id: string, name?: string) =>
  `${(name ?? id).replace(/\.[^.]+$/, '').replace(/_/g, ' ')} · đoạn ${Number(id.split('_c').pop()) + 1}`;
export const csvCell = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`;
export const fmtSeconds = (ms: number) => (ms / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 });

export function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  a.click(); URL.revokeObjectURL(url);
}

/** Mọi tài liệu của tài khoản (để chọn tài liệu ở không gian khác) và báo cáo đã lưu theo loại. */
export function useAnalysisData(kind: string) {
  const [allDocs, setAllDocs] = useState<Doc[]>([]);
  const [saved, setSaved] = useState<SavedReport[]>([]);
  useEffect(() => {
    getDocuments().then(setAllDocs).catch(() => setAllDocs([]));
    listReports(kind).then(setSaved).catch(() => setSaved([]));
  }, [kind]);
  const refreshSaved = async () => setSaved(await listReports(kind));
  return { allDocs, saved, setSaved, refreshSaved };
}

/** Đoạn tài liệu gốc khi bấm vào một căn cứ. */
export function useChunkViewer() {
  const [chunk, setChunk] = useState<{ id: string; source?: string; text?: string; error?: string } | null>(null);
  const show = async (id: string) => {
    setChunk({ id });
    try { const c = await getChunk(id); setChunk({ id, source: c.source_name, text: c.text }); } catch (e: any) { setChunk({ id, error: e.message }); }
  };
  const modal = chunk && (
    <StudioModal labelId="analysis-chunk" size="md" title="Đoạn tài liệu được trích" subtitle={chunk.source} onClose={() => setChunk(null)}>
      {chunk.error ? <p className="note is-error">{chunk.error}</p> : chunk.text ? <pre className="chunk-pre">{chunk.text}</pre> : <p className="muted-line"><span className="spin is-dark" />Đang tải…</p>}
    </StudioModal>
  );
  return { show, modal };
}

export function DocPicker({ docs, selected, onChange, exclude, disabled, legend }: {
  docs: Doc[]; selected: Set<string>; onChange: (next: Set<string>) => void; exclude?: string; disabled?: boolean; legend: string;
}) {
  const list = docs.filter(d => docId(d) !== exclude);
  const picked = list.filter(d => selected.has(docId(d))).length;
  const setAll = (on: boolean) => { const n = new Set(selected); list.forEach(d => (on ? n.add(docId(d)) : n.delete(docId(d)))); onChange(n); };
  return (
    <fieldset className="tv-field tv-picker" disabled={disabled}>
      <legend>{legend} <span className="tv-count">{picked}/{list.length}</span></legend>
      {list.length > 1 && <span className="tv-pick-all">
        <button type="button" onClick={() => setAll(true)} disabled={disabled || picked === list.length}>Chọn tất cả</button>
        <button type="button" onClick={() => setAll(false)} disabled={disabled || picked === 0}>Bỏ chọn</button>
      </span>}
      <div className="tv-docs">{list.length === 0 ? <span className="is-muted">Chưa có tài liệu. Hãy tải tài liệu lên ở Không gian làm việc.</span> : list.map(d => {
        const on = selected.has(docId(d));
        return (
          <label key={docId(d)} className={`chip${on ? ' is-on' : ''}`}>
            <input type="checkbox" checked={on} onChange={e => { const n = new Set(selected); e.target.checked ? n.add(docId(d)) : n.delete(docId(d)); onChange(n); }} />
            {on ? <Check size={13} aria-hidden="true" /> : <FileText size={13} aria-hidden="true" />}
            <span>{d.source_file}</span>
          </label>
        );
      })}</div>
    </fieldset>
  );
}

export function SavedReportsSelect({ saved, onLoad, disabled }: { saved: SavedReport[]; onLoad: (id: string) => void; disabled?: boolean }) {
  if (saved.length === 0) return null;
  return (
    <label className="tv-saved"><span className="sr">Báo cáo đã lưu</span>
      <FolderOpen size={14} aria-hidden="true" />
      <select value="" onChange={e => e.target.value && onLoad(e.target.value)} disabled={disabled}>
        <option value="">Mở báo cáo đã lưu ({saved.length})</option>
        {saved.map(s => <option key={s.report_id} value={s.report_id}>{s.title}</option>)}
      </select>
    </label>
  );
}

// ---------------- Khung trình bày chung của các công cụ
export type Tone = 'trace' | 'design' | 'security' | 'consistency' | 'evaluation';
type IconType = React.ComponentType<{ size?: number }>;

/** Tiêu đề công cụ: ô biểu tượng theo màu nhận diện của công cụ, tên, mô tả và thao tác bên phải. */
// Dòng nhóm phía trên tiêu đề, cùng kiểu với landing (gạch nhấn + chữ xanh).
const KICKER: Record<string, string> = {
  'Tổng quan': 'Hoạt động của hệ thống', 'Hồ sơ tài liệu': 'Công cụ phân tích', 'Đối chiếu yêu cầu': 'Bộ công cụ', 'Chất lượng yêu cầu': 'Bộ công cụ', 'Gói thiết kế kỹ thuật': 'Bộ công cụ',
  'Rà soát bảo mật': 'Bộ công cụ', 'Rà soát theo tiêu chí': 'Bộ công cụ', 'Kiểm tra điều kiện': 'Bộ công cụ', 'Quy trình từng bước': 'Bộ công cụ',
  'Xét duyệt theo danh sách': 'Bộ công cụ', 'Tạo câu hỏi ôn tập': 'Bộ công cụ', 'Tra cứu quy chế theo Điều': 'Bộ công cụ', 'Tính phép năm và tiền làm thêm giờ': 'Bộ công cụ',
  'Duyệt đơn từ': 'Bộ công cụ', 'Hỏi đáp chính sách cho nhân viên': 'Bộ công cụ', 'Rà soát hợp đồng': 'Bộ công cụ', 'Hồ sơ thủ tục': 'Bộ công cụ', 'Hiệu lực văn bản': 'Bộ công cụ', 'Kiểm tra mâu thuẫn': 'Công cụ phân tích', 'Phòng đánh giá': 'Nghiên cứu', 'Chấm mù': 'Nghiên cứu', 'Thực nghiệm': 'Nghiên cứu', 'Cơ sở dữ liệu': 'Quản trị', 'Người dùng': 'Quản trị', 'Tổ chức': 'Cộng tác', 'Kết quả đã lưu': 'Lưu trữ cá nhân', 'Thư viện tài liệu': 'Kho tri thức', 'Cài đặt': 'Tài khoản và hệ thống', 'Việc cần làm': 'Đơn từ và thông báo',
};
export function ToolHeader({ Icon, title, desc, right }: { Icon: IconType; title: string; desc: string; right?: React.ReactNode }) {
  return (
    <header className="tl-head">
      <span className="tl-mark" aria-hidden="true"><Icon size={20} /></span>
      <div className="tl-text"><p className="tl-kicker"><Icon size={14} aria-hidden="true" />{KICKER[title] ?? 'OrchestrIQ Studio'}</p><h1>{title}</h1><p>{desc}</p></div>
      {right && <div className="tl-right">{right}</div>}
    </header>
  );
}

/** Các bước thật của quy trình, sáng dần theo tiến độ. */
export function ProcessRail({ steps }: { steps: { label: string; state: 'done' | 'current' | 'todo' }[] }) {
  return (
    <ol className="tl-rail" aria-label="Tiến trình">
      {steps.map((s, i) => (
        <li key={s.label} className={`is-${s.state}`} aria-current={s.state === 'current' ? 'step' : undefined}>
          <span className="tl-dot">{s.state === 'done' ? '✓' : i + 1}</span><span className="tl-label">{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

/** Thanh phân bố kết quả (xanh/vàng/đỏ theo tỷ lệ) kèm chú thích số và dòng số đo phụ. */
export function DistributionBar({ segments, meta }: { segments: { label: string; value: number; tone: 'ok' | 'warn' | 'bad' | 'muted' }[]; meta?: React.ReactNode }) {
  const total = segments.reduce((n, s) => n + s.value, 0) || 1;
  return (
    <section className="tl-dist" aria-label="Phân bố kết quả">
      <div className="tl-bar">{segments.filter(s => s.value > 0).map(s => <i key={s.label} className={`is-${s.tone}`} style={{ flexGrow: s.value }} title={`${s.label}: ${s.value}`} />)}</div>
      <div className="tl-legend">
        {segments.map(s => <span key={s.label}><i className={`is-${s.tone}`} /><b>{s.value}</b> {s.label} <em>{Math.round((s.value / total) * 100)}%</em></span>)}
        {meta && <span className="tl-meta">{meta}</span>}
      </div>
    </section>
  );
}

export function EmptyState({ Icon, title, text, action }: { Icon: IconType; title: string; text: string; action?: React.ReactNode }) {
  return (
    <div className="tl-empty">
      <span className="tl-mark" aria-hidden="true"><Icon size={22} /></span>
      <h2>{title}</h2><p>{text}</p>{action}
    </div>
  );
}
