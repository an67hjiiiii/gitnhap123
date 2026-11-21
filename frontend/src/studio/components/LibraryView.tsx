// Thư viện tài liệu (đợt 6, mục 2b): xem, lọc, sắp xếp mọi tài liệu; loại tài liệu AI nhận ra (sửa được); mức mật;
// lối vào Hồ sơ tài liệu, Kiểm tra cả kho và Kiểm tra mâu thuẫn (trước là trang riêng trên thanh bên).
import { FileIcon } from './FileIcon';
import React, { useMemo, useRef, useState } from 'react';
import { Activity, AlertTriangle, ArrowUpRight, CheckCircle2, Copy, FileSearch, HelpCircle, History, XCircle, FileText, Filter, GitCompareArrows, Library, Search, Upload } from 'lucide-react';
import { DOC_TYPES, setDocType , libraryQuality, LibraryQuality, documentValidity, DocValidity } from '../services/api';
import type { DocumentInfo } from '../types';
import { ToolHeader } from './analysis/shared';
import '../styles/pages-2b.css';

const CLS: Record<string, string> = { PRIVATE: 'Riêng tư', COMPANY: 'Toàn tổ chức', DEPARTMENT: 'Nội bộ phòng', RESTRICTED: 'Hạn chế', SECRET: 'Mật' };
const extOf = (name: string) => (name.split('.').pop() || '').toLowerCase().slice(0, 4);
type Sort = 'name' | 'type' | 'chunks' | 'new';

type Props = {
  docs: DocumentInfo[];
  onOpenProfile: (sourceId: string) => void;
  onOpenConsistency: () => void;
  onAsk: (sourceId: string, name: string) => void;
  onUploadFile: (file: File) => Promise<void>;
};

export const LibraryView: React.FC<Props> = ({ docs, onOpenProfile, onOpenConsistency, onAsk, onUploadFile }) => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [q, setQ] = useState('');
  const [type, setType] = useState('');
  const [sort, setSort] = useState<Sort>('name');
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [drag, setDrag] = useState(false);
  // Sức khỏe kho (Đợt 7): số thật từ máy chủ (kiểm tra chất lượng, luật hiệu lực văn bản), không ước tính
  const [health, setHealth] = useState<LibraryQuality | null>(null);
  const [validity, setValidity] = useState<Record<string, DocValidity>>({});
  const idsKey = docs.map(d => String(d.id)).join(',');
  React.useEffect(() => {
    if (!docs.length) { setHealth(null); setValidity({}); return; }
    let alive = true;
    libraryQuality().then(q => alive && setHealth(q)).catch(() => alive && setHealth(null));
    documentValidity(docs.slice(0, 60).map(d => String(d.id))).then(r => alive && setValidity(Object.fromEntries(r.documents.map(x => [x.source_id, x])))).catch(() => undefined);
    return () => { alive = false; };
  }, [idsKey]);
  const failed = docs.filter(d => d.status === 'failed').length;
  const replaced = Object.values(validity).filter(v => v.status === 'REPLACED').length;
  const issues = (health?.docs ?? []).flatMap(d => d.issues.filter(i => i.level !== 'low').map(i => ({ name: d.source_name, id: d.source_id, msg: i.message })));
  const upload = async (list?: FileList | File[] | null) => {
    const files = Array.from(list ?? []); if (!files.length) return; setUploading(true); setError('');
    const errors: string[] = [];
    for (const f of files) { try { await onUploadFile(f); } catch (err: any) { errors.push(`${f.name}: ${err.message || 'Không tải được tệp.'}`); } }
    if (errors.length) setError(errors.join(' · '));
    setUploading(false);
  };
  const dropProps = {
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); setDrag(true); },
    onDragLeave: () => setDrag(false),
    onDrop: (e: React.DragEvent) => { e.preventDefault(); setDrag(false); void upload(e.dataTransfer.files); },
  };
  const typeOf = (d: DocumentInfo) => edits[String(d.id)] ?? d.doc_type ?? '';
  const counts = useMemo(() => docs.reduce<Record<string, number>>((m, d) => {
    const t = edits[String(d.id)] ?? d.doc_type ?? 'none';
    m[t] = (m[t] || 0) + 1;
    return m;
  }, {}), [docs, edits]);
  const shown = useMemo(() => {
    const k = q.trim().toLowerCase();
    const of = (d: DocumentInfo) => edits[String(d.id)] ?? d.doc_type ?? '';
    const list = docs.filter(d => (!k || d.source_file.toLowerCase().includes(k)) && (!type || of(d) === type));
    const by: Record<Sort, (a: DocumentInfo, b: DocumentInfo) => number> = {
      name: (a, b) => a.source_file.localeCompare(b.source_file, 'vi'),
      type: (a, b) => (DOC_TYPES[of(a)] ?? 'zz').localeCompare(DOC_TYPES[of(b)] ?? 'zz', 'vi'),
      chunks: (a, b) => (b.chunks_count || 0) - (a.chunks_count || 0),
      new: (a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')),
    };
    return [...list].sort(by[sort]);
  }, [docs, q, type, sort, edits]);
  const change = async (d: DocumentInfo, t: string) => {
    setError('');
    try { await setDocType(String(d.id), t); setEdits(m => ({ ...m, [String(d.id)]: t })); }
    catch (e: any) { setError(e.message || 'Không đổi được loại tài liệu.'); }
  };
  // tài liệu cá nhân: luôn là của mình; tài liệu tổ chức: chỉ người tải lên sửa nhãn (khớp backend)
  const canEdit = (d: DocumentInfo) => d.classification === undefined || d.mine === true;

  return (
    <main className="pg tl tone-overview lib">
      <div className="pg-col">
        <ToolHeader Icon={Library} title="Thư viện tài liệu"
          desc="Mọi tài liệu của không gian đang mở: loại tài liệu hệ thống tự nhận (bấm để sửa nếu sai), mức mật, số đoạn. Mở hồ sơ, kiểm tra cả kho hoặc tìm mâu thuẫn từ đây."
          right={<>
            <input ref={fileRef} type="file" hidden multiple accept=".pdf,.docx,.xlsx,.md,.txt,.sql,.png,.jpg,.jpeg,.tif,.tiff"
              onChange={e => { const fs = Array.from(e.target.files ?? []); e.target.value = ''; void upload(fs); }} />
            <button className="btn btn-dark" onClick={() => fileRef.current?.click()} disabled={uploading}>{uploading ? <span className="spin" /> : <Upload size={15} />}Thêm tài liệu</button></>} />

        {docs.length > 0 && <section className="lib-kpis" aria-label="Lọc theo loại tài liệu">
          <button type="button" className={`lib-kpi${type === '' ? ' is-on' : ''}`} aria-pressed={type === ''} onClick={() => setType('')}><b>{docs.length}</b><span>Tất cả</span></button>
          {Object.entries(DOC_TYPES).filter(([k]) => counts[k]).map(([k, v]) => (
            <button key={k} type="button" className={`lib-kpi${type === k ? ' is-on' : ''}`} aria-pressed={type === k} onClick={() => setType(type === k ? '' : k)}>
              <b>{counts[k]}</b><span>{v}</span></button>))}
          {counts.none > 0 && <span className="lib-kpi is-static"><b>{counts.none}</b><span>Chưa phân loại</span></span>}
        </section>}

        <section className="lib-tools">
          <button type="button" className="lib-tool" onClick={() => onOpenProfile(shown[0] ? String(shown[0].id) : '')}>
            <span className="lib-tool-ico"><FileSearch size={18} /></span><span><b>Hồ sơ tài liệu</b><small>Tóm tắt, thuật ngữ, sơ đồ tư duy, chất lượng, kiểm tra cả kho</small></span><ArrowUpRight size={16} /></button>
          <button type="button" className="lib-tool" onClick={onOpenConsistency}>
            <span className="lib-tool-ico"><GitCompareArrows size={18} /></span><span><b>Kiểm tra mâu thuẫn</b><small>Cặp câu cùng chủ đề khác con số hoặc ngược nghĩa giữa các tài liệu</small></span><ArrowUpRight size={16} /></button>
        </section>

        {docs.length > 0 && (() => {
          const dups = health?.duplicates ?? [];
          const unknown = (counts.none || 0) + (counts.other || 0);
          const total = health ? issues.length + dups.length + failed + unknown : null;
          const stats = [
            { n: health ? issues.length : null, label: 'Vấn đề chất lượng', tone: issues.length ? 'warn' : 'ok', Icon: AlertTriangle },
            { n: health ? dups.length : null, label: 'Cặp có thể trùng', tone: dups.length ? 'warn' : 'ok', Icon: Copy },
            { n: failed, label: 'Lỗi lập chỉ mục', tone: failed ? 'bad' : 'ok', Icon: XCircle },
            { n: unknown, label: 'Chưa rõ loại', tone: unknown ? 'warn' : 'ok', Icon: HelpCircle },
            { n: replaced, label: 'Bản đã bị thay thế', tone: replaced ? 'info' : 'ok', Icon: History },
          ];
          return <section className="dz-card lib-health hx2" aria-label="Sức khỏe kho tài liệu">
            <header className="hx2-head">
              <span className="hx2-ico" aria-hidden="true"><Activity size={18} /></span>
              <span className="hx2-title"><b>Sức khỏe kho</b><small>Kiểm tra trên {docs.length} tài liệu · cập nhật khi danh sách thay đổi</small></span>
              <span className={`hx2-pill is-${total === null ? 'idle' : total ? 'warn' : 'ok'}`}>
                {total === null ? 'Đang kiểm tra…' : total ? `${total} mục cần xem` : <><CheckCircle2 size={14} />Ổn định</>}</span>
            </header>
            <div className="hx2-stats">
              {stats.map(({ n, label, tone, Icon }) => <div key={label} className={`hx2-stat is-${n === null ? 'idle' : tone}`}>
                <span className="hx2-stat-ico" aria-hidden="true">{n === 0 ? <CheckCircle2 size={15} /> : <Icon size={15} />}</span>
                <b>{n === null ? '…' : n}</b><small>{label}</small></div>)}
            </div>
            {(issues.length > 0 || dups.length > 0) && <ul className="hx2-list">
              {dups.slice(0, 3).map(d => <li key={d.a_id + d.b_id} className="hx2-row">
                <span className="hx2-tag is-dup"><Copy size={13} />Trùng</span>
                <div className="hx2-body">
                  <div className="hx2-pair"><span className="hx2-doc"><FileIcon name={d.a} size={18} /><span>{d.a}</span></span>
                    <span className="hx2-vs" aria-hidden="true">≈</span>
                    <span className="hx2-doc"><FileIcon name={d.b} size={18} /><span>{d.b}</span></span></div>
                  <small>Nội dung giống nhau {Math.round(d.score * 100)}%. Nên giữ một bản hoặc đánh dấu bản cũ đã bị thay thế.</small>
                </div>
                <span className="hx2-meter" title={`Giống nhau ${Math.round(d.score * 100)}%`}><i style={{ width: `${Math.round(d.score * 100)}%` }} /><em>{Math.round(d.score * 100)}%</em></span>
              </li>)}
              {issues.slice(0, 4).map((i, k) => <li key={k} className="hx2-row">
                <span className="hx2-tag is-q"><AlertTriangle size={13} />Chất lượng</span>
                <div className="hx2-body">
                  <span className="hx2-doc"><FileIcon name={i.name} size={18} /><span>{i.name}</span></span>
                  <small>{i.msg}</small>
                </div>
                <button type="button" className="hx2-go" onClick={() => onOpenProfile(i.id)}>Xem hồ sơ<ArrowUpRight size={14} /></button>
              </li>)}
            </ul>}
          </section>;
        })()}

        <section className={`dz-card lib-table-card${drag ? ' is-drag' : ''}`} {...dropProps}>
          <div className="lib-bar">
            <label className="lib-find"><Search size={15} /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm theo tên tài liệu" aria-label="Tìm theo tên tài liệu" /></label>
            <label className="lib-sort"><Filter size={14} />
              <select value={sort} onChange={e => setSort(e.target.value as Sort)} aria-label="Sắp xếp">
                <option value="name">Tên A–Z</option><option value="type">Loại tài liệu</option><option value="chunks">Nhiều đoạn nhất</option><option value="new">Mới nhất</option>
              </select></label>
          </div>
          {error && <p className="note is-error" role="alert">{error}</p>}
          {docs.length === 0 ? <button type="button" className="lib-drop" onClick={() => fileRef.current?.click()} disabled={uploading}>
              <span className="lib-drop-files" aria-hidden="true"><i>PDF</i><i>DOCX</i><i>XLSX</i></span>
              <b>{uploading ? 'Đang nạp tài liệu…' : 'Kéo thả tài liệu vào đây hoặc bấm để chọn tệp'}</b>
              <small>PDF, Word, Excel, Markdown, TXT, ảnh chụp văn bản. Hệ thống tự nhận loại tài liệu, chia đoạn và lập chỉ mục trên máy chủ của bạn.</small>
            </button>
            : shown.length === 0 ? <p className="lib-empty">Không có tài liệu khớp bộ lọc.</p>
            : <ul className="lib-list">{shown.map(d => {
              const t = typeOf(d);
              return <li key={String(d.id)}>
                <span className="lib-ext is-file" aria-hidden="true"><FileIcon name={d.source_file} size={30} /></span>
                <div className="lib-name"><b title={d.source_file}>{d.source_file}</b><small>{[`${d.chunks_count} đoạn`, d.file_size_kb ? `${d.file_size_kb < 1024 ? `${Math.round(d.file_size_kb)} KB` : `${(d.file_size_kb / 1024).toFixed(1)} MB`}` : '', d.created_at ? new Date(d.created_at).toLocaleDateString('vi-VN') : '', d.owner && !d.mine ? `của ${d.owner}` : ''].filter(Boolean).join(' · ')}{d.status === 'failed' && <em className="lib-fail"> · nạp lỗi</em>}</small></div>
                {canEdit(d)
                  ? <label className="lib-type"><span className="sr">Loại tài liệu của {d.source_file}</span>
                      <select value={t} onChange={e => change(d, e.target.value)}>
                        {!t && <option value="">Chưa phân loại</option>}
                        {Object.entries(DOC_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                      </select></label>
                  : <span className="lib-type is-ro">{DOC_TYPES[t] ?? 'Chưa phân loại'}</span>}
                {d.classification && <span className={`lib-cls is-${d.classification.toLowerCase()}`}>{CLS[d.classification] ?? d.classification}</span>}
                {d.status === 'failed' && <span className="lib-flag is-bad" title="Tài liệu chưa lập chỉ mục được; tải lại tệp hoặc xem Hồ sơ">Lỗi lập chỉ mục</span>}
                {validity[String(d.id)]?.status === 'REPLACED' && <span className="lib-flag is-old" title={validity[String(d.id)].status_note}>Bản cũ</span>}
                {(validity[String(d.id)]?.replaces.length ?? 0) > 0 && validity[String(d.id)]?.status !== 'REPLACED' && <span className="lib-flag is-new" title={`Thay thế ${validity[String(d.id)].replaces.join(', ')}`}>Bản mới</span>}
                <span className="lib-acts">
                  <button type="button" className="btn btn-ghost is-sm" onClick={() => onOpenProfile(String(d.id))}>Hồ sơ</button>
                  <button type="button" className="btn btn-ghost is-sm" onClick={() => onAsk(String(d.id), d.source_file)}>Hỏi</button>
                </span>
              </li>;
            })}</ul>}
        </section>
      </div>
    </main>
  );
};
