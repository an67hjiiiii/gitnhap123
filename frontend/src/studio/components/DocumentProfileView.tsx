// Hồ sơ tài liệu: tóm tắt, thuật ngữ, câu hỏi gợi ý, tài liệu liên quan, chất lượng và thông tin riêng tư, so sánh phiên bản.
// Phần chạy tại máy (chất lượng, riêng tư, liên quan, so dòng) không gọi mô hình; phần viết lời (tóm tắt, câu hỏi, định nghĩa) gọi mô hình cục bộ.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Hash, LayoutGrid, ListTree, ShieldCheck, BookMarked, BookOpen, Download, EyeOff, FileSearch, FileText, Gauge, GitCompare, Library, Link2, MessageCircleQuestion, Network, RefreshCw, ShieldAlert, Sparkles, X } from 'lucide-react';
import {
  buildMindmap, compareDocs, DocCompare, getReport, GlossaryTerm, libraryQuality, LibraryQuality, listReports, Measured, MindMap, profileGlossary, profileLocal,
  ProfileLocal, profileMasked, profileQuestions, profileSummary, ProfileSummary, SavedReport, saveReport, SuggestedQuestion, updateReport,
  DOC_TYPES, setDocType,
} from '../services/api';
import { DocumentReader } from './DocumentReader';
import { DocCover, Marked, ProfilePreview, QualityRing, Stat, useProfileMotion } from './profile/ProfileParts';
import './profile/profile.css';
import { MindMapCanvas } from './MindMap';
import { ExportButtons } from './analysis/exporters';
import { baseName, chunkLabel, csvCell, Doc, docId, download, EmptyState, fmtSeconds, ProcessRail, ToolHeader, useAnalysisData, useChunkViewer } from './analysis/shared';

interface Profile {
  source_id: string; source_name: string; created_at: string;
  local: ProfileLocal; summary?: ProfileSummary; questions?: SuggestedQuestion[]; glossary?: GlossaryTerm[];
  measured: Measured; errors: string[];
}
type Tab = 'overview' | 'mindmap' | 'glossary' | 'questions' | 'related' | 'quality' | 'compare';
const STEPS = ['Đọc tài liệu tại máy', 'Tóm tắt', 'Câu hỏi gợi ý', 'Thuật ngữ'];
const LEVEL: Record<string, string> = { high: 'Cao', medium: 'Trung bình', low: 'Thấp' };
const add = (a: Measured, b?: Partial<Measured>) => ({ input_tokens: a.input_tokens + (b?.input_tokens || 0), output_tokens: a.output_tokens + (b?.output_tokens || 0), latency_ms: a.latency_ms + (b?.latency_ms || 0) });

export const DocumentProfileView: React.FC<{ docs: Doc[]; onAsk: (question: string, sourceId: string, sourceName: string) => void; initialSourceId?: string }> = ({ docs, onAsk, initialSourceId }) => {
  const { allDocs, saved, refreshSaved } = useAnalysisData('doc_profile');
  const viewer = useChunkViewer();
  const pickable = allDocs.length ? allDocs : docs;
  const [sourceId, setSourceId] = useState(initialSourceId ?? '');  // mở từ Thư viện: đúng tài liệu đã chọn
  // nhãn loại tài liệu (tự nhận khi tải lên, người tải lên sửa được); sửa xong giữ tại chỗ tới khi tải lại danh sách
  const [typeEdits, setTypeEdits] = useState<Record<string, string>>({});
  const [typeError, setTypeError] = useState('');
  const curDoc = pickable.find(d => docId(d) === sourceId) as (Doc & { doc_type?: string | null; mine?: boolean; classification?: string }) | undefined;
  const docType = typeEdits[sourceId] ?? curDoc?.doc_type ?? '';
  const canEditType = !!curDoc && (curDoc.classification === undefined || curDoc.mine === true);
  const changeType = async (t: string) => {
    setTypeError('');
    try { await setDocType(sourceId, t); setTypeEdits(m => ({ ...m, [sourceId]: t })); }
    catch (e: any) { setTypeError(e.message || 'Không đổi được loại tài liệu.'); }
  };
  const [profile, setProfile] = useState<Profile | null>(null);
  const [step, setStep] = useState(-1);
  const [tab, setTab] = useState<Tab>('overview');
  const [error, setError] = useState<string | null>(null);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [compareWith, setCompareWith] = useState('');
  const [cmp, setCmp] = useState<DocCompare | null>(null);
  const [cmpBusy, setCmpBusy] = useState(false);
  const [cmpFilter, setCmpFilter] = useState<'all' | 'added' | 'removed' | 'changed'>('all');
  const [reader, setReader] = useState<{ id: string; name?: string } | null>(null);
  const [library, setLibrary] = useState(false);
  const running = step >= 0;

  useEffect(() => { if (!sourceId && pickable.length) setSourceId(docId(pickable[0])); }, [pickable, sourceId]);
  const savedFor = useMemo(() => {
    const name = pickable.find(d => docId(d) === sourceId)?.source_file;
    return saved.find(s => s.title === name);
  }, [saved, pickable, sourceId]);
  // Mở hồ sơ đã lưu của tài liệu đang chọn (nếu có) để không phải chạy lại mô hình.
  useEffect(() => {
    setProfile(null); setCmp(null); setError(null);
    if (!savedFor) return;
    let alive = true; setLoadingSaved(true);
    getReport(savedFor.report_id).then(r => { if (alive && r.payload?.source_id === sourceId) setProfile(r.payload); })
      .catch(e => alive && setError(e.message)).finally(() => alive && setLoadingSaved(false));
    return () => { alive = false; };
  }, [savedFor?.report_id, sourceId]);

  const build = async () => {
    if (!sourceId) return;
    setError(null); setCmp(null); setTab('overview');
    const errors: string[] = [];
    let measured: Measured = { input_tokens: 0, output_tokens: 0, latency_ms: 0 };
    try {
      setStep(0);
      const local = await profileLocal(sourceId);
      let p: Profile = { source_id: sourceId, source_name: local.source_name, created_at: new Date().toISOString(), local, measured, errors };
      setProfile(p);
      const run = async <T extends Partial<Measured>>(i: number, fn: () => Promise<T>, apply: (r: T) => Partial<Profile>) => {
        setStep(i);
        try { const r = await fn(); measured = add(measured, r); p = { ...p, ...apply(r), measured }; setProfile(p); }
        catch (e: any) { errors.push(`${STEPS[i]}: ${e.message}`); p = { ...p, errors: [...errors] }; setProfile(p); }
      };
      await run(1, () => profileSummary(sourceId), r => ({ summary: r }));
      await run(2, () => profileQuestions(sourceId), r => ({ questions: r.questions }));
      await run(3, () => profileGlossary(sourceId), r => ({ glossary: r.terms }));
      if (savedFor) await updateReport(savedFor.report_id, p, p.source_name);
      else await saveReport({ kind: 'doc_profile', title: p.source_name, payload: p });
      await refreshSaved();
    } catch (e: any) { setError(e.message); }
    finally { setStep(-1); }
  };

  const runCompare = async () => {
    if (!compareWith || !sourceId) return;
    setCmpBusy(true); setError(null);
    try { setCmp(await compareDocs(sourceId, compareWith, true)); } catch (e: any) { setError(e.message); } finally { setCmpBusy(false); }
  };

  const downloadMasked = async () => {
    try { const r = await profileMasked(sourceId); download(`${baseName(r.source_name)}_da-che.md`, r.masked_text, 'text/markdown'); }
    catch (e: any) { setError(e.message); }
  };

  const profileMarkdown = () => {
    if (!profile) return '';
    const p = profile, q = p.local.quality;
    const lines = [
      `# Hồ sơ tài liệu: ${p.source_name}`, '', `Lập lúc ${new Date(p.created_at).toLocaleString('vi-VN')}. ${p.summary?.doc_type ? `Loại: ${p.summary.doc_type}.` : ''}`, '',
      '## Tóm tắt', p.summary?.summary || '(chưa có)', '', ...(p.summary?.key_points || []).map(k => `- ${k}`), '',
      '## Thuật ngữ', ...(p.glossary || p.local.glossary_defined).map(t => `- **${t.term}**: ${t.definition}${t.origin === 'model' ? ' _(mô hình giải thích)_' : ''}`), '',
      '## Câu hỏi gợi ý', ...(p.questions || []).map(x => `- ${x.question}`), '',
      '## Tài liệu liên quan', ...p.local.related.map(r => `- ${r.source_name} (độ trùng ${Math.round(r.score * 100)}%): ${r.shared_terms.join(', ')}`), '',
      `## Chất lượng: ${q.score}/100`, ...(q.issues.length ? q.issues.map(i => `- [${LEVEL[i.level]}] ${i.message}`) : ['- Không phát hiện vấn đề.']), '',
      '## Thông tin nhạy cảm', ...(p.local.pii.findings.length ? p.local.pii.findings.map(f => `- Dòng ${f.line}: ${f.label} ${f.masked}`) : ['- Không phát hiện.']),
    ];
    return lines.join('\n');
  };

  const exportCompare = () => cmp && download(`so-sanh_${baseName(cmp.old_name)}_${baseName(cmp.new_name)}.csv`,
    ['Loại,Mục,Nội dung', ...cmp.changes.map(c => [TYPE[c.type], c.section, c.text].map(csvCell).join(','))].join('\n'), 'text/csv');

  const local = profile?.local;
  const terms = profile?.glossary ?? local?.glossary_defined ?? [];
  const piiTotal = local?.pii.findings.length ?? 0;
  const curName = pickable.find(d => docId(d) === sourceId)?.source_file || profile?.source_name || '';
  const pfRef = useRef<HTMLDivElement>(null);
  useProfileMotion(pfRef, `${profile?.created_at ?? 'none'}|${sourceId}|${tab}`);
  const shownChanges = (cmp?.changes || []).filter(c => cmpFilter === 'all' || (cmpFilter === 'changed' ? c.type.startsWith('changed') : c.type === cmpFilter));

  return (
    <main className="pg tl tone-profile">
      <div className="pg-col tv-col">
        <ToolHeader Icon={FileSearch} title="Hồ sơ tài liệu" desc="Hiểu một tài liệu trong một phút: tóm tắt, thuật ngữ, câu hỏi nên hỏi, độ tin cậy của nội dung và thông tin nhạy cảm cần che."
          right={<button className="btn btn-ghost" onClick={() => setLibrary(v => !v)} aria-expanded={library}><Library size={15} />Kiểm tra cả kho</button>} />
        {library && <LibraryPanel onClose={() => setLibrary(false)} onOpen={(id, name) => { setSourceId(id); setLibrary(false); setReader({ id, name }); }} />}

        <div className="pf" ref={pfRef}>
          <section className="pf-hero pf-in">
            <DocCover ext={curName.split('.').pop() || ''} />
            <div className="pf-id">
              <div className="pf-tags">
                {docType ? (canEditType
                  ? <label className="pf-tag is-type pf-doctype" title="Hệ thống tự nhận khi tải lên; bấm để sửa nếu nhận sai">
                      <span className="sr">Loại tài liệu</span>
                      <select value={docType} onChange={e => changeType(e.target.value)} disabled={running}>
                        {Object.entries(DOC_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                      </select><ChevronDown size={12} aria-hidden="true" />
                    </label>
                  : <span className="pf-tag is-type">{DOC_TYPES[docType] ?? docType}</span>)
                  : profile?.summary?.doc_type && !/loại tài liệu/i.test(profile.summary.doc_type) && <span className="pf-tag is-type">{profile.summary.doc_type}</span>}
                {local && <span className="pf-tag">{local.quality.chunks} đoạn</span>}
                {profile && savedFor && !running && <span className="pf-tag is-ok"><CheckCircle2 size={13} />Đã lưu</span>}
                {running && <span className="pf-tag is-run"><span className="spin is-dark" />{STEPS[step]}…</span>}
              </div>
              <label className="pf-switch" title="Đổi tài liệu">
                <span className="sr">Tài liệu</span>
                <select value={sourceId} onChange={e => setSourceId(e.target.value)} disabled={running}>
                  {pickable.length === 0 && <option value="">Chưa có tài liệu</option>}
                  {pickable.map(d => <option key={docId(d)} value={docId(d)}>{d.source_file.replace(/\.[^.]+$/, '').replace(/_/g, ' ')}</option>)}
                </select>
                <ChevronDown size={20} aria-hidden="true" />
              </label>
              {typeError && <p className="note is-error" role="alert">{typeError}</p>}
              <p className="pf-meta">{profile
                ? <>Lập lúc {new Date(profile.created_at).toLocaleString('vi-VN')}{profile.measured.latency_ms > 0 && <> · mô hình dùng <b>{profile.measured.input_tokens + profile.measured.output_tokens > 0 ? (profile.measured.input_tokens + profile.measured.output_tokens).toLocaleString('vi-VN') : 0}</b> token trong <b>{fmtSeconds(profile.measured.latency_ms)}</b> giây</>}</>
                : loadingSaved ? 'Đang mở hồ sơ đã lưu…' : 'Tài liệu này chưa có hồ sơ.'}</p>
              <div className="pf-actions">
                <button className="btn btn-dark pf-cta" onClick={build} disabled={!sourceId || running}>
                  {running ? <><span className="spin" />Đang lập hồ sơ</> : profile ? <><RefreshCw size={15} />Lập lại hồ sơ</> : <><Sparkles size={15} />Lập hồ sơ</>}
                </button>
                {sourceId && <button className="btn btn-ghost" onClick={() => setReader({ id: sourceId, name: curName })}><BookOpen size={15} />Đọc toàn văn</button>}
                {profile && !running && <ExportButtons title={`Hồ sơ tài liệu: ${profile.source_name}`} markdown={profileMarkdown()} filename={`ho-so_${baseName(profile.source_name)}`} />}
              </div>
              {running && <ProcessRail steps={STEPS.map((label, i) => ({ label, state: i < step ? 'done' : i === step ? 'current' : 'todo' }))} />}
              {profile?.errors.map(e => <p key={e} className="note is-error">{e}</p>)}
              {error && <p className="note is-error" role="alert">{error}</p>}
            </div>
            <QualityRing score={local ? local.quality.score : null} />
          </section>

          {profile && local && <div className="pf-stats">
            <Stat Icon={FileText} value={local.quality.words} label="từ" sub={local.quality.chunks ? `khoảng ${Math.round(local.quality.words / local.quality.chunks).toLocaleString('vi-VN')} từ mỗi đoạn` : undefined} />
            <Stat Icon={ListTree} value={local.quality.headings} label="đề mục" sub="Bấm để xem sơ đồ" onClick={() => setTab('mindmap')} />
            <Stat Icon={Hash} value={local.quality.requirement_ids} label="mã yêu cầu" sub="FR, NFR, UC…" />
            <Stat Icon={BookMarked} value={terms.length} label="thuật ngữ" sub={`${terms.filter(t => t.origin === 'document').length} định nghĩa có trong tài liệu`} onClick={() => setTab('glossary')} />
            <Stat Icon={piiTotal ? ShieldAlert : ShieldCheck} value={piiTotal} label="thông tin nhạy cảm" tone={piiTotal ? 'bad' : 'ok'} sub={piiTotal ? 'Cần che trước khi chia sẻ' : 'Không phát hiện'} onClick={() => setTab('quality')} />
          </div>}

          {sourceId && <div className="tabs pf-tabs" role="tablist" aria-label="Mục của hồ sơ">
            {([['overview', 'Tổng quan', LayoutGrid], ['mindmap', 'Sơ đồ tư duy', Network], ['glossary', 'Thuật ngữ', BookMarked, terms.length], ['questions', 'Câu hỏi gợi ý', MessageCircleQuestion, profile?.questions?.length], ['related', 'Liên quan', Link2, local?.related.length],
              ['quality', 'Chất lượng & riêng tư', Gauge, local ? local.quality.issues.length + piiTotal || undefined : undefined], ['compare', 'So sánh phiên bản', GitCompare]] as [Tab, string, React.ComponentType<{ size?: number }>, number?][]).map(([id, label, I, n]) => (
              <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'is-on' : ''} onClick={() => setTab(id)}><I size={15} />{label}{n ? <span className="tab-n">{n}</span> : null}</button>
            ))}
          </div>}

        {tab === 'mindmap' && sourceId ? <MindMapPanel sourceId={sourceId} sourceName={curName} onShowChunk={viewer.show} /> : !profile ? (loadingSaved ? <p className="muted-line"><span className="spin is-dark" />Đang mở hồ sơ đã lưu…</p> :
          <ProfilePreview action={<button className="btn btn-dark pf-cta" onClick={build} disabled={!sourceId || running}>{running ? <><span className="spin" />Đang lập hồ sơ</> : <><Sparkles size={15} />Lập hồ sơ cho tài liệu này</>}</button>} />
        ) : <>

          {tab === 'overview' && <div className="pf-bento">
            <section className="dz-card pf-summary pf-in">
              <header><h3><FileText size={16} />Tóm tắt</h3>{profile.summary && <small className="is-muted">mô hình đọc {profile.summary.chunks_read}/{profile.summary.chunks_total} đoạn</small>}</header>
              {profile.summary ? <>
                <p className="pf-lead"><Marked text={profile.summary.summary} /></p>
                {profile.summary.key_points.length > 0 && <>
                  <h4>Ý chính</h4>
                  <ol className="pf-points">{profile.summary.key_points.map((k, n) => <li key={k}><span className="pf-num">{n + 1}</span><p><Marked text={k} /></p></li>)}</ol>
                </>}
                {profile.summary.chunks_read < profile.summary.chunks_total && <p className="tl-note"><AlertTriangle size={14} />Tài liệu dài: mô hình đọc {profile.summary.chunks_read}/{profile.summary.chunks_total} đoạn, rải đều từ đầu đến cuối.</p>}
              </> : <p className="is-muted">{running ? 'Đang tóm tắt…' : 'Chưa có tóm tắt (bước này lỗi hoặc chưa chạy).'}</p>}
            </section>
            <aside className="pf-side">
              <section className="dz-card pf-in">
                <header><h3><MessageCircleQuestion size={16} />Hỏi nhanh</h3>{(profile.questions?.length ?? 0) > 3 && <button className="dp-link" onClick={() => setTab('questions')}>Tất cả {profile.questions!.length}</button>}</header>
                {profile.questions?.length ? <div className="pf-asks">{profile.questions.slice(0, 3).map(q => (
                  <button key={q.question} className="pf-ask" onClick={() => onAsk(q.question, profile.source_id, profile.source_name)}><span>{q.question}</span><ArrowRight size={16} /></button>
                ))}</div> : <p className="is-muted">{running ? 'Đang soạn câu hỏi…' : 'Chưa có câu hỏi gợi ý.'}</p>}
              </section>
              <section className="dz-card pf-in">
                <header><h3><BookMarked size={16} />Thuật ngữ chính</h3>{terms.length > 0 && <button className="dp-link" onClick={() => setTab('glossary')}>Tất cả {terms.length}</button>}</header>
                {terms.length ? <div className="pf-terms">{terms.slice(0, 10).map(t => <button key={t.term} className={`pf-term${t.origin === 'document' ? ' is-doc' : ''}`} title={t.definition} onClick={() => setTab('glossary')}>{t.term}</button>)}</div>
                  : <p className="is-muted">Không thấy thuật ngữ.</p>}
              </section>
              <section className="dz-card pf-in">
                <header><h3><Link2 size={16} />Cùng chủ đề</h3>{local!.related.length > 3 && <button className="dp-link" onClick={() => setTab('related')}>Tất cả {local!.related.length}</button>}</header>
                {local!.related.length ? <div className="pf-rels">{local!.related.slice(0, 3).map(r => (
                  <button key={r.source_id} className="pf-rel" onClick={() => setReader({ id: r.source_id, name: r.source_name })} title={`Từ chung: ${r.shared_terms.join(', ')}`}>
                    <span className="pf-rel-n">{r.source_name.replace(/\.[^.]+$/, '').replace(/_/g, ' ')}</span><b>{Math.round(r.score * 100)}%</b>
                    <span className="pf-rel-bar"><i style={{ width: `${Math.round(r.score * 100)}%` }} /></span>
                  </button>))}</div> : <p className="is-muted">Chưa có tài liệu khác để so.</p>}
              </section>
            </aside>
          </div>}

          {tab === 'glossary' && (terms.length === 0 ? <EmptyState Icon={BookMarked} title="Không thấy thuật ngữ" text="Tài liệu không có mục định nghĩa và không có từ kỹ thuật lặp lại đủ nhiều." /> :
            <div className="tbl tv-table dp-terms"><table><thead><tr><th>Thuật ngữ</th><th>Nghĩa</th><th>Nguồn</th></tr></thead><tbody>
              {terms.map(t => <tr key={t.term}><td><b>{t.term}</b></td><td>{t.definition}{t.context && <small className="dp-ctx">“{t.context}”</small>}</td>
                <td><span className={`dp-origin is-${t.origin}`}>{t.origin === 'document' ? 'Trong tài liệu' : 'Mô hình giải thích'}</span></td></tr>)}
            </tbody></table></div>)}

          {tab === 'questions' && (!profile.questions?.length ? <EmptyState Icon={MessageCircleQuestion} title="Chưa có câu hỏi gợi ý" text="Bước này chưa chạy hoặc mô hình không đề xuất được câu hỏi trả lời được từ tài liệu." /> :
            <ul className="dp-questions">{profile.questions.map(q => <li key={q.question}>
              <p>{q.question}</p>
              {q.chunk_id && <button className="tv-cite-count" onClick={() => viewer.show(q.chunk_id!)}>{chunkLabel(q.chunk_id, profile.source_name)}</button>}
              <button className="btn btn-dark is-sm" onClick={() => onAsk(q.question, profile.source_id, profile.source_name)}>Hỏi ngay<ArrowRight size={14} /></button>
            </li>)}</ul>)}

          {tab === 'related' && (local!.related.length === 0 ? <EmptyState Icon={Link2} title="Chưa có tài liệu khác để so" text="Nạp thêm tài liệu của dự án để thấy tài liệu nào cùng chủ đề." /> :
            <ul className="dp-related">{local!.related.map(r => <li key={r.source_id}>
              <div><button type="button" className="dp-link" onClick={() => setReader({ id: r.source_id, name: r.source_name })}>{r.source_name}</button><span className="dp-meter"><i style={{ width: `${Math.round(r.score * 100)}%` }} /></span><em>{Math.round(r.score * 100)}%</em></div>
              <p>Từ chung: {r.shared_terms.join(', ') || '—'}</p>
              <span className="dp-rel-act"><button className="btn btn-dark is-sm" onClick={() => setReader({ id: r.source_id, name: r.source_name })}><BookOpen size={14} />Đọc toàn văn</button>
              <button className="btn btn-ghost is-sm" onClick={() => setSourceId(r.source_id)}>Xem hồ sơ</button></span>
            </li>)}<li className="tl-note">Độ trùng tính theo tần suất từ ngữ chung (cosine), chạy tại máy.</li></ul>)}

          {tab === 'quality' && <div className="dz-grid">
            <section className="dz-card">
              <header><h3><Gauge size={16} />Chất lượng nội dung</h3><span className={`cht-status is-${local!.quality.score >= 80 ? 'complete' : local!.quality.score >= 50 ? 'partial' : 'failed'}`}>{local!.quality.score}/100</span></header>
              {local!.quality.issues.length === 0 ? <p>Không phát hiện vấn đề làm hệ thống trả lời kém (quá ngắn, lỗi mã hóa, đoạn trùng, thiếu đề mục).</p> :
                <ul className="dp-issues">{local!.quality.issues.map(i => <li key={i.code} className={`is-${i.level}`}><span>{LEVEL[i.level]}</span>{i.message}</li>)}</ul>}
            </section>
            <section className="dz-card">
              <header><h3><ShieldAlert size={16} />Thông tin nhạy cảm</h3>
                {piiTotal > 0 && <button className="btn btn-ghost is-sm" onClick={downloadMasked}><EyeOff size={14} />Tải bản đã che</button>}</header>
              {piiTotal === 0 ? <p>Không phát hiện email, số điện thoại, CCCD/CMND, số tài khoản, số thẻ (đã kiểm tra Luhn) hay khóa bí mật.</p> : <>
                <p>{Object.entries(local!.pii.counts).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(' · ')}. Giá trị chỉ hiện ở dạng đã che; bản đã che thay mỗi giá trị bằng [ĐÃ CHE].</p>
                <div className="tbl tv-table"><table><thead><tr><th>Dòng</th><th>Loại</th><th>Giá trị (đã che)</th></tr></thead><tbody>
                  {local!.pii.findings.map((f, i) => <tr key={i}><td>{f.line}</td><td>{f.label}</td><td><code>{f.masked}</code></td></tr>)}
                </tbody></table></div>
              </>}
            </section>
          </div>}

          {tab === 'compare' && <div className="dz-grid">
            <section className="tv-setup">
              <p className="tl-note"><GitCompare size={14} />Chọn phiên bản mới của <b>{profile.source_name}</b> (đã nạp thành tài liệu riêng). Hệ thống so từng dòng tại máy rồi để mô hình tóm tắt thay đổi.</p>
              <div className="dp-pick">
                <label className="tv-field"><span>Phiên bản mới</span>
                  <select value={compareWith} onChange={e => setCompareWith(e.target.value)} disabled={cmpBusy}>
                    <option value="">Chọn tài liệu…</option>
                    {pickable.filter(d => docId(d) !== sourceId).map(d => <option key={docId(d)} value={docId(d)}>{d.source_file}</option>)}
                  </select>
                </label>
                <div className="tv-actions">
                  <button className="btn btn-dark" onClick={runCompare} disabled={!compareWith || cmpBusy}>{cmpBusy ? <><span className="spin" />Đang so sánh…</> : <><GitCompare size={15} />So sánh</>}</button>
                  {cmp && <button className="btn btn-ghost" onClick={exportCompare}><Download size={15} />Tải danh sách (.csv)</button>}
                </div>
              </div>
            </section>
            {cmp && <>
              {cmp.similarity < 0.3 && <p className="note is-warn"><AlertTriangle size={15} />Hai tài liệu chỉ giống nhau {Math.round(cmp.similarity * 100)}%; có thể đây là hai tài liệu khác nhau chứ không phải hai phiên bản.</p>}
              <div className="dp-kpis is-4">
                <div><b>{Math.round(cmp.similarity * 100)}%</b><span>giống nhau</span></div>
                <div className="is-ok"><b>{cmp.added}</b><span>dòng thêm</span></div>
                <div className="is-no"><b>{cmp.removed}</b><span>dòng bỏ</span></div>
                <div className="is-mid"><b>{cmp.changed}</b><span>dòng sửa</span></div>
              </div>
              {cmp.summary?.summary && <section className="dz-card"><header><h3><GitCompare size={16} />Tóm tắt thay đổi</h3><small className="is-muted">{fmtSeconds(cmp.summary.latency_ms)} giây</small></header><p>{cmp.summary.summary}</p></section>}
              <div className="tv-seg" role="group" aria-label="Lọc thay đổi">
                {(['all', 'added', 'removed', 'changed'] as const).map(f => <button key={f} className={cmpFilter === f ? 'is-on' : ''} onClick={() => setCmpFilter(f)}>{{ all: 'Tất cả', added: 'Thêm', removed: 'Bỏ', changed: 'Sửa' }[f]}</button>)}
              </div>
              <ol className="dp-diff">{shownChanges.map((c, i) => <li key={i} className={`is-${c.type}`}>
                <span>{TYPE[c.type]}</span><p>{c.text}</p>{c.section && <small>{c.section.replace(/^#+\s*/, '')}</small>}
              </li>)}</ol>
              {cmp.truncated && <p className="tl-note">Chỉ hiện 300 thay đổi đầu tiên.</p>}
            </>}
          </div>}
        </>}
        </div>
      </div>
      {viewer.modal}
      {reader && <DocumentReader key={reader.id} sourceId={reader.id} sourceName={reader.name} onClose={() => setReader(null)} />}
    </main>
  );
};

// Sơ đồ tư duy: "Theo cấu trúc" dựng ngay từ đề mục (tại máy); "AI tóm lược" do mô hình cục bộ gom ý, được lưu để mở lại.
function MindMapPanel({ sourceId, sourceName, onShowChunk }: { sourceId: string; sourceName: string; onShowChunk: (id: string) => void }) {
  const [mode, setMode] = useState<'outline' | 'ai'>('outline');
  const [maps, setMaps] = useState<{ outline?: MindMap; ai?: MindMap }>({});
  const [busy, setBusy] = useState<'outline' | 'ai' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedReport[]>([]);
  const savedAi = saved.find(r => r.title === sourceName);
  useEffect(() => { listReports('mindmap').then(setSaved).catch(() => setSaved([])); }, []);
  useEffect(() => { setMaps({}); setError(null); }, [sourceId]);
  useEffect(() => {
    if (mode !== 'outline' || maps.outline) return;
    let alive = true; setBusy('outline'); setError(null);
    buildMindmap(sourceId, 'outline').then(m => alive && setMaps(x => ({ ...x, outline: m }))).catch(e => alive && setError(e.message)).finally(() => alive && setBusy(null));
    return () => { alive = false; };
  }, [mode, sourceId, maps.outline]);
  useEffect(() => {
    if (mode !== 'ai' || maps.ai || !savedAi) return;
    let alive = true;
    getReport(savedAi.report_id).then(r => { if (alive && r.payload?.source_id === sourceId) setMaps(x => ({ ...x, ai: r.payload })); }).catch(e => alive && setError(e.message));
    return () => { alive = false; };
  }, [mode, savedAi?.report_id, sourceId, maps.ai]);
  const buildAi = async () => {
    setBusy('ai'); setError(null);
    try {
      const m: MindMap = { ...await buildMindmap(sourceId, 'ai'), created_at: new Date().toISOString() };
      setMaps(x => ({ ...x, ai: m }));
      if (savedAi) await updateReport(savedAi.report_id, m, sourceName); else await saveReport({ kind: 'mindmap', title: sourceName, payload: m });
      setSaved(await listReports('mindmap'));
    } catch (e: any) { setError(e.message); } finally { setBusy(null); }
  };
  const map = maps[mode];
  return <section className="dp-mind">
    <div className="dp-mind-head">
      <div className="tv-seg" role="group" aria-label="Cách lập sơ đồ">
        <button className={mode === 'outline' ? 'is-on' : ''} onClick={() => setMode('outline')}>Theo cấu trúc</button>
        <button className={mode === 'ai' ? 'is-on' : ''} onClick={() => setMode('ai')}><Sparkles size={13} />AI tóm lược</button>
      </div>
      <p className="tl-note">{mode === 'outline' ? 'Dựng ngay từ đề mục và gạch đầu dòng của tài liệu, giữ đúng thứ tự gốc. Chạy tại máy.'
        : 'Mô hình cục bộ gom ý thành 4–7 nhánh chủ đề và nối các ý liên quan giữa các nhánh (nét đứt). Mỗi nút trỏ về đoạn tài liệu sinh ra nó.'}</p>
      {mode === 'ai' && <button className="btn btn-dark" onClick={buildAi} disabled={busy === 'ai'}>{busy === 'ai' ? <><span className="spin" />Đang lập sơ đồ…</> : map ? <><RefreshCw size={15} />Lập lại</> : <><Network size={15} />Lập sơ đồ</>}</button>}
    </div>
    {error && <p className="note is-error" role="alert">{error}</p>}
    {map ? <>
      {map.mode === 'ai' && <p className="tl-note">Lập lúc {map.created_at ? new Date(map.created_at).toLocaleString('vi-VN') : '—'} · {map.nodes} ý
        {map.latency_ms ? <> · {((map.input_tokens || 0) + (map.output_tokens || 0)).toLocaleString('vi-VN')} token trong {fmtSeconds(map.latency_ms)} giây</> : null}
        {map.chunks_read && map.chunks_total && map.chunks_read < map.chunks_total ? <> · mô hình đọc {map.chunks_read}/{map.chunks_total} đoạn</> : null}</p>}
      <MindMapCanvas root={map.root} links={map.links} fileName={`so-do_${baseName(sourceName)}`} onShowChunk={onShowChunk} />
    </> : busy ? <p className="muted-line"><span className="spin is-dark" />{busy === 'ai' ? 'Mô hình đang đọc tài liệu và gom ý, thường mất 30–60 giây…' : 'Đang dựng sơ đồ…'}</p>
      : mode === 'ai' && <EmptyState Icon={Network} title="Chưa có sơ đồ AI cho tài liệu này" text="Bấm Lập sơ đồ để mô hình cục bộ gom tài liệu thành các nhánh chủ đề. Sơ đồ được lưu để lần sau mở lại ngay." />}
  </section>;
}

// Kiểm tra cả kho: tài liệu trùng nhau, quá ít nội dung, không trích được chữ (bản scan), lỗi mã hóa, thiếu đề mục.
function LibraryPanel({ onClose, onOpen }: { onClose: () => void; onOpen: (id: string, name: string) => void }) {
  const [data, setData] = useState<LibraryQuality | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { libraryQuality().then(setData).catch(e => setError(e.message)); }, []);
  return <section className="dz-card dp-lib">
    <header><h3><Library size={16} />Kiểm tra cả kho tài liệu</h3><button className="icon-btn is-sm" onClick={onClose} aria-label="Đóng"><X size={15} /></button></header>
    {error ? <p className="note is-error">{error}</p> : !data ? <p className="muted-line"><span className="spin is-dark" />Đang đọc toàn bộ kho…</p> : <>
      <div className="dp-kpis is-4">
        <div><b>{data.documents}</b><span>tài liệu</span></div>
        <div className={data.with_issues ? 'is-mid' : 'is-ok'}><b>{data.with_issues}</b><span>có vấn đề</span></div>
        <div className={data.duplicates.length ? 'is-no' : 'is-ok'}><b>{data.duplicates.length}</b><span>cặp trùng nhau</span></div>
        <div className={data.docs.some(d => d.chunks === 0) ? 'is-no' : 'is-ok'}><b>{data.docs.filter(d => d.chunks === 0).length}</b><span>không đọc được chữ</span></div>
      </div>
      {data.duplicates.length > 0 && <p className="note is-warn"><AlertTriangle size={15} />{data.duplicates.map(p => `${p.a} ≈ ${p.b} (${Math.round(p.score * 100)}%)`).join('; ')}. Nên giữ một bản để câu trả lời không bị lặp nguồn.</p>}
      <div className="tbl tv-table"><table><thead><tr><th>Tài liệu</th><th>Điểm</th><th>Vấn đề</th></tr></thead><tbody>
        {data.docs.map(d => <tr key={d.source_id}>
          <td><button type="button" className="dp-link" onClick={() => onOpen(d.source_id, d.source_name)} disabled={!d.chunks}>{d.source_name}</button><small className="dp-ctx">{d.words.toLocaleString('vi-VN')} từ · {d.chunks} đoạn</small></td>
          <td><span className={`cht-status is-${d.score >= 80 ? 'complete' : d.score >= 50 ? 'partial' : 'failed'}`}>{d.score}</span></td>
          <td>{d.issues.length === 0 ? <span className="is-muted">Không có</span> : <ul className="dp-issues">{d.issues.map(i => <li key={i.code} className={`is-${i.level}`}><span>{LEVEL[i.level]}</span>{i.message}</li>)}</ul>}</td>
        </tr>)}
      </tbody></table></div>
      <p className="tl-note">Chạy tại máy. Hệ thống chưa nhận dạng chữ trong ảnh (OCR), nên bản scan được báo là "không đọc được chữ" thay vì "mờ".</p>
    </>}
  </section>;
}

const TYPE: Record<string, string> = { added: 'Thêm', removed: 'Bỏ', changed_from: 'Bản cũ', changed_to: 'Bản mới' };
