// Kết quả đã lưu (đợt 6, mục 2b): mở lại những gì AI đã làm (hồ sơ tài liệu, mâu thuẫn, gói thiết kế, đánh giá…).
// Báo cáo lưu ở backend (/studio/reports) theo từng người; mở = đi tới công cụ đã tạo ra nó (công cụ tự nạp bản đã lưu).
import React, { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Archive, ClipboardCheck, FileSearch, GitCompareArrows, RefreshCw, Search, Trash2, Wrench } from 'lucide-react';
import { deleteReport, exportDocx, getChunk, getReport, listAllReports, SavedReport, updateReport } from '../services/api';
import { StudioModal } from './StudioModal';
import { Markdown } from '../utils/markdown';
import { saveBlob } from './analysis/exporters';
import { BookOpen, FileDown, Pencil, Save } from 'lucide-react';
import type { NavigationTab } from '../types';
import { ToolHeader } from './analysis/shared';
import '../styles/pages-2b.css';
import '../styles/results-hub.css';

// loại báo cáo → tên hiển thị, trang công cụ mở lại được, màu nhận diện
const KINDS: Record<string, { label: string; tab?: NavigationTab; hue: string }> = {
  doc_profile: { label: 'Hồ sơ tài liệu', tab: 'documents', hue: 'blue' },
  mindmap: { label: 'Sơ đồ tư duy', tab: 'documents', hue: 'blue' },
  consistency: { label: 'Kiểm tra mâu thuẫn', tab: 'consistency', hue: 'amber' },
  evaluation: { label: 'Phòng đánh giá', tab: 'evaluation', hue: 'green' },
  eval_set: { label: 'Bộ câu hỏi đánh giá', tab: 'evaluation', hue: 'green' },
  design: { label: 'Gói thiết kế', tab: 'toolkit', hue: 'violet' },
  req_quality: { label: 'Chất lượng yêu cầu', tab: 'toolkit', hue: 'violet' },
  security_review: { label: 'Rà soát bảo mật', tab: 'toolkit', hue: 'red' },
  traceability: { label: 'Rà soát theo tiêu chí', tab: 'toolkit', hue: 'violet' },
  criteria: { label: 'Danh mục tiêu chí', tab: 'toolkit', hue: 'violet' },
  answer: { label: 'Câu trả lời', hue: 'blue' },            // Đợt 6: mở ngay tại đây, sửa trước khi xuất
  compare: { label: 'So sánh phiên bản', tab: 'compare', hue: 'amber' },
};
// những công cụ tạo ra kết quả lưu được
const MAKERS: { tab: NavigationTab; title: string; desc: string; Icon: typeof FileSearch }[] = [
  { tab: 'documents', title: 'Lập hồ sơ tài liệu', desc: 'Tóm tắt, thuật ngữ, sơ đồ tư duy', Icon: FileSearch },
  { tab: 'consistency', title: 'Kiểm tra mâu thuẫn', desc: 'Câu trái nhau giữa các tài liệu', Icon: GitCompareArrows },
  { tab: 'toolkit', title: 'Kỹ năng', desc: 'Rà soát, gói thiết kế, câu hỏi ôn tập…', Icon: Wrench },
  { tab: 'evaluation', title: 'Phòng đánh giá', desc: 'So sánh cách trả lời trên bộ câu hỏi', Icon: ClipboardCheck },
];
const when = (r: SavedReport) => new Date(r.updated_at ?? r.created_at);
const DAY = 86400000;
function group(d: Date) {
  const start = new Date(); start.setHours(0, 0, 0, 0);
  if (d >= start) return 'Hôm nay';
  if (d.getTime() >= start.getTime() - 6 * DAY) return '7 ngày qua';
  return 'Cũ hơn';
}

type Props = { onOpen: (tab: NavigationTab, report: SavedReport) => void; onGo: (tab: NavigationTab) => void };

/** Câu trả lời đã lưu: sửa nội dung trước khi xuất Word; nguồn đi kèm tệp. Mở đoạn nguồn thì máy chủ kiểm quyền lại. */
function AnswerViewer({ id, onClose }: { id: string; onClose: () => void }) {
  const [r, setR] = useState<SavedReport | null>(null);
  const [text, setText] = useState('');
  const [edit, setEdit] = useState(false);
  const [msg, setMsg] = useState('');
  const [src, setSrc] = useState<Record<string, string>>({});
  useEffect(() => { getReport(id).then(x => { setR(x); setText(x.payload?.markdown ?? ''); }).catch(e => setMsg(e.message)); }, [id]);
  const cites: string[] = r?.payload?.citations ?? [];
  const openCite = (c: string) => getChunk(c).then(x => setSrc(s => ({ ...s, [c]: `${x.source_name}: ${x.text.slice(0, 400)}` }))).catch(e => setSrc(s => ({ ...s, [c]: e.message })));
  const withSources = () => `# ${r?.payload?.question || r?.title}\n\n${text}` + (cites.length ? `\n\n## Nguồn\n\n${cites.map(c => `- ${c}`).join('\n')}` : '');
  return <StudioModal labelId="sav-answer" icon={<BookOpen size={18} />} title={r?.title || 'Câu trả lời đã lưu'} subtitle={r ? `Lưu lúc ${new Date(r.updated_at ?? r.created_at).toLocaleString('vi-VN')}` : 'Đang tải…'} onClose={onClose}
    footer={<>{msg && <span className="sav-msg">{msg}</span>}
      <button className="btn btn-ghost" onClick={() => setEdit(e => !e)}><Pencil size={14} />{edit ? 'Xem' : 'Sửa'}</button>
      {edit && <button className="btn btn-ghost" onClick={() => r && updateReport(r.report_id, { ...r.payload, markdown: text }).then(() => setMsg('Đã lưu thay đổi')).catch(e => setMsg(e.message))}><Save size={14} />Lưu thay đổi</button>}
      <button className="btn btn-dark" disabled={!r} onClick={async () => { try { saveBlob(`tra-loi_${id.slice(-8)}.docx`, await exportDocx(withSources())); } catch (e: any) { setMsg(e.message); } }}><FileDown size={14} />Xuất Word kèm nguồn</button></>}>
    {r?.payload?.question && <p className="sav-q"><b>Câu hỏi:</b> {r.payload.question}</p>}
    {edit ? <textarea className="sav-edit" value={text} onChange={e => setText(e.target.value)} rows={14} aria-label="Sửa nội dung câu trả lời" />
      : <div className="md"><Markdown text={text} /></div>}
    {cites.length > 0 && <div className="sav-cites"><b>Nguồn</b>{cites.map(c => <div key={c}><button type="button" className="skc-cite" onClick={() => openCite(c)}>{r?.payload?.sources?.[cites.indexOf(c)] ?? c}</button>{src[c] && <small>{src[c]}</small>}</div>)}</div>}
  </StudioModal>;
}

export const SavedResultsView: React.FC<Props> = ({ onOpen, onGo }) => {
  const [viewing, setViewing] = useState<string | null>(null);
  const [rows, setRows] = useState<SavedReport[] | null>(null);
  const [kind, setKind] = useState('');
  const [q, setQ] = useState('');
  const [error, setError] = useState('');
  const load = () => { setError(''); listAllReports().then(setRows).catch(e => setError(e.message)); };
  useEffect(load, []);
  const all = rows ?? [];
  const byKind = useMemo(() => Object.entries(all.reduce<Record<string, number>>((m, r) => ({ ...m, [r.kind]: (m[r.kind] || 0) + 1 }), {}))
    .sort((a, b) => b[1] - a[1]), [all]);
  const shown = useMemo(() => {
    const k = q.trim().toLowerCase();
    return all.filter(r => (!kind || r.kind === kind) && (!k || r.title.toLowerCase().includes(k)))
      .sort((a, b) => when(b).getTime() - when(a).getTime());
  }, [all, kind, q]);
  const groups = useMemo(() => shown.reduce<[string, SavedReport[]][]>((acc, r) => {
    const g = group(when(r)); const last = acc[acc.length - 1];
    if (last && last[0] === g) last[1].push(r); else acc.push([g, [r]]);
    return acc;
  }, []), [shown]);
  const latest = shown[0] && !kind && !q ? all.reduce((a, b) => (when(b) > when(a) ? b : a)) : null;
  const remove = async (r: SavedReport) => {
    if (!confirm(`Xóa kết quả đã lưu “${r.title}”? Không hoàn tác được.`)) return;
    try { await deleteReport(r.report_id); setRows(v => (v ?? []).filter(x => x.report_id !== r.report_id)); }
    catch (e: any) { setError(e.message); }
  };
  const desc = rows === null ? 'Đang tải danh sách…'
    : all.length === 0 ? 'Chưa có kết quả nào. Những gì bạn bấm “Lưu” trong các công cụ sẽ nằm ở đây để mở lại, sửa hoặc xuất.'
    : `${all.length} kết quả đã lưu${latest ? `, gần nhất: “${latest.title}” lúc ${when(latest).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })} ngày ${when(latest).toLocaleDateString('vi-VN')}` : ''}.`;

  return (
    <main className="pg tl tone-overview sav">
      {viewing && <AnswerViewer id={viewing} onClose={() => setViewing(null)} />}
      <div className="pg-col">
        <ToolHeader Icon={Archive} title="Kết quả đã lưu" desc={desc}
          right={<button className="btn btn-ghost" onClick={load} aria-label="Tải lại danh sách"><RefreshCw size={15} />Tải lại</button>} />
        {error && <p className="note is-error" role="alert">{error}</p>}
        <div className="sav-layout">
          <section className="dz-card sav-main" aria-label="Danh sách kết quả">
            {all.length > 0 && <div className="sav-bar">
              <label className="lib-find"><Search size={15} /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm theo tên kết quả" aria-label="Tìm theo tên kết quả" /></label>
              {byKind.length > 1 && <nav className="sav-kinds" aria-label="Lọc theo loại">
                <button type="button" className={!kind ? 'is-on' : ''} aria-pressed={!kind} onClick={() => setKind('')}>Tất cả <em>{all.length}</em></button>
                {byKind.map(([k, n]) => <button key={k} type="button" className={kind === k ? 'is-on' : ''} aria-pressed={kind === k} onClick={() => setKind(kind === k ? '' : k)}>
                  {KINDS[k]?.label ?? k} <em>{n}</em></button>)}
              </nav>}
            </div>}
            {rows === null && !error && <ul className="sav-skel" aria-hidden="true"><li /><li /><li /></ul>}
            {rows && all.length === 0 && <div className="sav-empty">
              <span className="sav-empty-art" aria-hidden="true"><i /><i /><i /></span>
              <b>Chưa lưu kết quả nào</b>
              <p>Lập hồ sơ một tài liệu rồi bấm “Lưu”: bản tóm tắt, thuật ngữ và sơ đồ tư duy sẽ nằm ở đây, mở lại không phải chạy lại mô hình.</p>
              <button type="button" className="btn btn-dark" onClick={() => onGo('documents')}><FileSearch size={15} />Lập hồ sơ tài liệu</button>
            </div>}
            {all.length > 0 && shown.length === 0 && <p className="lib-empty">Không có kết quả khớp bộ lọc.</p>}
            {groups.map(([g, list]) => <section key={g} className="sav-group" aria-label={g}>
              <h3>{g} <em>{list.length}</em></h3>
              <ul className="sav-rows">{list.map(r => {
                const k = KINDS[r.kind];
                return <li key={r.report_id} className="sav-row" data-hue={k?.hue ?? 'slate'}>
                  <span className="sav-kind">{k?.label ?? r.kind}</span>
                  <b className="sav-title" title={r.title}>{r.title}</b>
                  <time dateTime={when(r).toISOString()}>{when(r).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })} · {when(r).toLocaleDateString('vi-VN')}</time>
                  <span className="sav-acts">
                    {r.kind === 'answer' ? <button type="button" className="btn btn-dark is-sm" onClick={() => setViewing(r.report_id)}><ArrowUpRight size={14} />Mở</button>
                      : k?.tab && <button type="button" className="btn btn-dark is-sm" onClick={() => onOpen(k.tab!, r)}><ArrowUpRight size={14} />Mở</button>}
                    <button type="button" className="btn btn-ghost is-sm" onClick={() => remove(r)} aria-label={`Xóa ${r.title}`} title="Xóa"><Trash2 size={14} /></button>
                  </span>
                </li>;
              })}</ul>
            </section>)}
          </section>

          <aside className="sav-side">
            <section className="dz-card sav-make">
              <h3>Tạo kết quả mới</h3>
              {MAKERS.map(({ tab, title, desc: d, Icon }) => <button key={tab} type="button" className="sav-maker" onClick={() => onGo(tab)}>
                <Icon size={17} aria-hidden="true" /><span><b>{title}</b><small>{d}</small></span><ArrowUpRight size={15} aria-hidden="true" /></button>)}
            </section>
            {byKind.length > 0 && <section className="dz-card sav-mix">
              <h3>Theo loại</h3>
              <ul>{byKind.map(([k, n]) => <li key={k} data-hue={KINDS[k]?.hue ?? 'slate'}>
                <span>{KINDS[k]?.label ?? k}</span><b>{n}</b>
                <i style={{ width: `${Math.max(6, (n / all.length) * 100)}%` }} aria-hidden="true" /></li>)}</ul>
            </section>}
          </aside>
        </div>
      </div>
    </main>
  );
};
