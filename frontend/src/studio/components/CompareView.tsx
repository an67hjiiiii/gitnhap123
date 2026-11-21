// So sánh phiên bản (Đợt 4): chọn hai tài liệu, đối chiếu theo Chương/Điều/Khoản bằng mã, lọc loại thay đổi,
// xem song song có tô chỗ khác, mở nguồn, xuất Word/Excel, lưu vào Kết quả. Không gọi mô hình; quyền kiểm ở máy chủ.
import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowLeftRight, Archive, BookOpen, CheckCircle2, ChevronDown, FileDown, FilePlus2, FileSpreadsheet, Filter, GitCompareArrows, Info, Sparkles } from 'lucide-react';
import { FileIcon } from './FileIcon';
import { canSaveReports, compareVersions, documentValidity, DocValidity, exportDocx, saveReport, VersionCompare, VersionItem } from '../services/api';
import { ToolHeader } from './analysis/shared';
import { saveBlob } from './analysis/exporters';
import { DocumentReader } from './DocumentReader';
import { CHANGE_LABEL, Change, changeTone, compareCsv, compareMarkdown, wordDiff } from '../utils/compareText';
import '../styles/pages-2b.css';
import '../styles/compare.css';

type Doc = { id?: number | string; source_file: string };
const ORDER: Change[] = ['ADDED', 'MODIFIED', 'MOVED_MODIFIED', 'MOVED', 'REMOVED', 'UNCHANGED'];

function Diff({ a, b, side }: { a: string; b: string; side: 'old' | 'new' }) {
  const parts = useMemo(() => wordDiff(a, b), [a, b]);
  return <>{parts.filter(p => p.op === 'same' || p.op === (side === 'old' ? 'del' : 'add')).map((p, i) =>
    p.op === 'same' ? <React.Fragment key={i}>{p.t}</React.Fragment> : <mark key={i} className={side === 'old' ? 'cv-del' : 'cv-add'}>{p.t}</mark>)}</>;
}

export const CompareView: React.FC<{ docs: Doc[]; workspaceId?: number | string; initial?: { old: string; new: string } | null }> = ({ docs, workspaceId, initial }) => {
  const ids = docs.map(d => String(d.id ?? ''));
  const [oldId, setOldId] = useState(initial?.old ?? '');
  const [newId, setNewId] = useState(initial?.new ?? '');
  const [validity, setValidity] = useState<DocValidity[]>([]);
  const [result, setResult] = useState<VersionCompare | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState<Set<Change>>(new Set(ORDER.filter(c => c !== 'UNCHANGED')));
  const [reader, setReader] = useState<{ id: string; name: string } | null>(null);
  const [saved, setSaved] = useState('');

  useEffect(() => {
    if (!ids.length) return;
    documentValidity(ids.slice(0, 60)).then(r => setValidity(r.documents)).catch(() => setValidity([]));
  }, [ids.join(',')]);
  // cặp gợi ý: văn bản mới nêu "thay thế <số hiệu>" của văn bản cũ trong kho
  const pairs = useMemo(() => validity.flatMap(n => n.replaces.map(num => validity.find(o => o.number === num)).filter(Boolean).map(o => ({ old: o!, new: n }))), [validity]);
  const confirmed = pairs.some(p => p.old.source_id === oldId && p.new.source_id === newId);
  const nameOf = (id: string) => docs.find(d => String(d.id) === id)?.source_file ?? id;

  const run = async (o = oldId, n = newId) => {
    if (!o || !n || o === n) { setError('Chọn hai tài liệu khác nhau: bản cũ và bản mới.'); return; }
    setBusy(true); setError(null); setSaved('');
    try { setResult(await compareVersions(o, n)); } catch (e: any) { setResult(null); setError(e.message); } finally { setBusy(false); }
  };
  useEffect(() => { if (initial?.old && initial?.new) { setOldId(initial.old); setNewId(initial.new); void run(initial.old, initial.new); } }, [initial?.old, initial?.new]);

  const items = (result?.items ?? []).filter(it => show.has(it.change));
  const toggle = (c: Change) => setShow(s => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n; });
  const base = result ? `so-sanh_${result.old.source_name.replace(/\.\w+$/, '')}_${result.new.source_name.replace(/\.\w+$/, '')}`.slice(0, 80) : 'so-sanh';
  const word = async () => { if (!result) return; try { saveBlob(`${base}.docx`, await exportDocx(compareMarkdown(result.old.source_name, result.new.source_name, result.items))); } catch (e: any) { setError(e.message); } };
  const csv = () => { if (result) saveBlob(`${base}.csv`, new Blob([compareCsv(result.items)], { type: 'text/csv;charset=utf-8' })); };
  const save = async () => {
    if (!result) return;
    try { await saveReport({ kind: 'compare', title: `${result.old.source_name} → ${result.new.source_name}`, workspace_id: workspaceId ? String(workspaceId) : null, payload: result }); setSaved('Đã lưu vào Kết quả'); }
    catch (e: any) { setError(e.message); }
  };

  const unit = (it: VersionItem, side: 'old' | 'new') => {
    const u = it[side], other = it[side === 'old' ? 'new' : 'old'];
    if (!u) return <div className={`cv-cell is-empty is-${side}`}>{side === 'old' ? 'Không có ở bản cũ' : 'Không còn ở bản mới'}</div>;
    const diff = other && (it.change === 'MODIFIED' || it.change === 'MOVED_MODIFIED');
    return <div className={`cv-cell is-${side}`}>
      <b>{u.key}{u.title ? `. ${u.title}` : ''}</b>{u.chapter && <small>{u.chapter}</small>}
      <p>{diff ? <Diff a={side === 'old' ? u.body : other!.body} b={side === 'old' ? other!.body : u.body} side={side} /> : u.body}</p>
    </div>;
  };

  return (
    <main className="pg tl tone-overview cv">
      <div className="pg-col">
        <ToolHeader Icon={GitCompareArrows} title="So sánh phiên bản"
          desc="Đối chiếu hai bản theo Chương, Điều, Khoản. Kết quả do mã tính (thêm, sửa, bỏ, giữ, di chuyển), không do mô hình viết; người có thẩm quyền xác nhận trước khi dùng." />
        {error && <p className="note is-error" role="alert">{error}</p>}

        <section className="dz-card cv-pick" aria-label="Chọn hai phiên bản">
          {(['old', 'new'] as const).map((side, k) => { const id = side === 'old' ? oldId : newId; const set = side === 'old' ? setOldId : setNewId;
            return <React.Fragment key={side}>
              {k === 1 && <button type="button" className="cv-swap" onClick={() => { setOldId(newId); setNewId(oldId); }} disabled={!oldId && !newId} aria-label="Đổi chỗ bản cũ và bản mới" title="Đổi chỗ"><ArrowLeftRight size={16} /></button>}
              <label className={`cv-slot is-${side}${id ? ' is-set' : ''}`}>
                <span className="cv-slot-tag">{side === 'old' ? 'Bản cũ' : 'Bản mới'}</span>
                <span className="cv-slot-box">
                  <span className="cv-slot-ico" aria-hidden="true">{id ? <FileIcon name={nameOf(id)} size={26} /> : <FilePlus2 size={18} />}</span>
                  <select value={id} onChange={e => set(e.target.value)} aria-label={side === 'old' ? 'Chọn bản cũ' : 'Chọn bản mới'}>
                    <option value="">{docs.length ? 'Chọn tài liệu…' : 'Chưa có tài liệu'}</option>{docs.map(d => <option key={String(d.id)} value={String(d.id)}>{d.source_file}</option>)}</select>
                  <ChevronDown size={16} className="cv-slot-car" aria-hidden="true" />
                </span>
              </label></React.Fragment>; })}
          <button className="btn cv-go" onClick={() => run()} disabled={busy || !oldId || !newId}>{busy ? <><span className="spin" />Đang đối chiếu…</> : <><GitCompareArrows size={16} />So sánh</>}</button>
          {pairs.length > 0 && <div className="cv-pairs"><Sparkles size={14} /><span>Gợi ý từ theo dõi tài liệu thay thế:</span>
            {pairs.map(p => <button key={p.old.source_id + p.new.source_id} type="button" onClick={() => { setOldId(p.old.source_id); setNewId(p.new.source_id); void run(p.old.source_id, p.new.source_id); }}>
              {p.new.number || p.new.source_name} thay thế {p.old.number || p.old.source_name}</button>)}</div>}
          {oldId && newId && oldId !== newId && <p className={`cv-confirm ${confirmed ? 'is-ok' : 'is-warn'}`}>
            {confirmed ? <><CheckCircle2 size={14} />Cặp đã xác nhận: bản mới nêu rõ thay thế bản cũ.</>
              : <><AlertTriangle size={14} />Cặp chưa được xác nhận: không thấy câu "thay thế {'<số hiệu>'}" trong bản mới. Kiểm tra lại đúng bản cũ/bản mới.</>}</p>}
          {docs.length < 2 && <p className="cv-confirm is-warn"><AlertTriangle size={14} />Cần ít nhất hai tài liệu trong không gian. Tải lên bản cũ và bản mới ở trang Tài liệu.</p>}
        </section>

        {result && <>
          <section className="cv-summary" aria-label="Tóm tắt thay đổi">
            {ORDER.map(c => <button key={c} type="button" className={`cv-stat is-${changeTone(c)}${show.has(c) ? ' is-on' : ''}`} aria-pressed={show.has(c)} onClick={() => toggle(c)}>
              <b>{result.counts[c] ?? 0}</b><span>{CHANGE_LABEL[c]}</span></button>)}
            <div className="cv-acts">
              <button className="btn btn-ghost is-sm" onClick={word}><FileDown size={14} />Word</button>
              <button className="btn btn-ghost is-sm" onClick={csv}><FileSpreadsheet size={14} />Excel (.csv)</button>
              {canSaveReports() && <button className="btn btn-dark is-sm" onClick={save} disabled={!!saved}><Archive size={14} />{saved || 'Lưu vào Kết quả'}</button>}
            </div>
          </section>
          <section className="dz-card cv-table" aria-label="Bảng đối chiếu">
            <div className="cv-head"><span>Thay đổi</span>
              <button type="button" onClick={() => setReader({ id: result.old.source_id, name: result.old.source_name })}><BookOpen size={14} />{result.old.source_name}</button>
              <button type="button" onClick={() => setReader({ id: result.new.source_id, name: result.new.source_name })}><BookOpen size={14} />{result.new.source_name}</button></div>
            {items.length === 0 ? <p className="cv-empty">Không có mục nào ở các loại đang chọn. Bấm các ô số phía trên để lọc.</p> : items.map((it, i) => (
              <article key={i} className={`cv-row is-${changeTone(it.change)}`}>
                <div className="cv-kind"><span className={`skc-badge is-${changeTone(it.change)}`}>{CHANGE_LABEL[it.change]}</span>
                  {it.clauses && it.clauses.length > 0 && <ul>{it.clauses.map(c => <li key={c.clause}>Khoản {c.clause}: {c.change === 'ADDED' ? 'thêm' : c.change === 'REMOVED' ? 'bỏ' : 'sửa'}</li>)}</ul>}
                  {it.numbers_changed && it.numbers_changed.length > 0 && <small>Số thay đổi: {it.numbers_changed.join(', ')}</small>}</div>
                {unit(it, 'old')}{unit(it, 'new')}
              </article>))}
          </section>
        </>}
        {!result && !busy && <section className="dz-card cv-intro">
          <h3>Cách dùng</h3>
          <ol className="cv-steps">
            {[
              { Icon: FilePlus2, b: 'Chọn hai bản', t: 'Bản cũ và bản mới, hoặc bấm một cặp gợi ý.' },
              { Icon: GitCompareArrows, b: 'Bấm So sánh', t: 'Mỗi Điều được ghép theo số và tiêu đề.' },
              { Icon: Filter, b: 'Lọc thay đổi', t: 'Bấm các ô số để chỉ xem loại cần xem; chỗ khác được tô màu.' },
              { Icon: FileDown, b: 'Xuất hoặc lưu', t: 'Tải Word, Excel hoặc lưu vào Kết quả để mở lại.' },
            ].map(({ Icon, b, t }, i) => <li key={b}><span className="cv-step-n">{i + 1}</span><span className="cv-step-ico" aria-hidden="true"><Icon size={17} /></span><b>{b}</b><small>{t}</small></li>)}
          </ol>
          <div className="cv-legend" aria-label="Chú giải màu">
            <span>Chú giải:</span>
            {ORDER.filter(c => c !== 'MOVED_MODIFIED').map(c => <span key={c} className={`skc-badge is-${changeTone(c)}`}>{CHANGE_LABEL[c]}</span>)}
            <span className="cv-legend-mk"><mark className="cv-del">chữ bị bỏ</mark><mark className="cv-add">chữ thêm mới</mark></span>
          </div>
          <p className="cv-note"><Info size={14} />Văn bản không có "Điều N" thì so theo tiêu đề mục. Chưa hỗ trợ bảng biểu và văn bản scan chưa nhận dạng chữ.</p>
        </section>}
      </div>
      {reader && <DocumentReader sourceId={reader.id} sourceName={reader.name} onClose={() => setReader(null)} />}
    </main>
  );
};
