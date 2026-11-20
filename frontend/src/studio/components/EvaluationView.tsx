// Phòng đánh giá thực nghiệm: bộ câu hỏi có ý chính, chạy A/B/C, chấm mù, thống kê cặp theo câu hỏi.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, BarChart3, CheckCircle2, ClipboardCheck, ChevronLeft, ChevronRight, Download, EyeOff, FlaskConical, ListOrdered, Plus, Save, Square, Trash2, X } from 'lucide-react';
import { Described, evalRun, EvalRunResult, evalStats, getReport, PairedComparison, saveReport, updateReport } from '../services/api';
import './profile/tools.css';
import { csvCell, Doc, DocPicker, docId, download, SavedReportsSelect, ToolHeader, useAnalysisData } from './analysis/shared';

type Question = { id: string; question: string; points: string[] };
type EvalSet = { name: string; questions: Question[] };
type Item = Partial<EvalRunResult> & { qid: string; condition: string; repeat: number; error?: string };
type Score = { correct: number; complete: number; grounded: number };
type Grades = Record<string, Record<string, Score>>;
type RunState = { set: EvalSet; conditions: string[]; repeats: number; sourceIds: string[]; items: Record<string, Item>; grades: Grades; started: string; finished?: string };

const CONDITIONS = ['A', 'B', 'C', 'C-P', 'C-N', 'C-O', 'AUTO'];
const COND_VI: Record<string, string> = { A: 'A · Vanilla RAG', B: 'B · Multi-Agent cơ bản', C: 'C · Điều phối đầy đủ', 'C-P': 'C-P · bỏ lập kế hoạch', 'C-N': 'C-N · bỏ chuẩn hóa', 'C-O': 'C-O · bỏ tối ưu ngữ cảnh', AUTO: 'AUTO · Tự quyết (như ô chat)' };
const CRITERIA: [keyof Score, string][] = [['correct', 'Đúng'], ['complete', 'Đủ ý'], ['grounded', 'Có căn cứ']];
const key = (qid: string, cond: string, rep: number) => `${qid}|${cond}|${rep}`;
const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const num = (v: number | null | undefined, d = 1) => (v == null ? '—' : v.toLocaleString('vi-VN', { maximumFractionDigits: d }));
const pFmt = (p: number | null) => (p == null ? '—' : p < 0.001 ? '< 0,001' : p.toLocaleString('vi-VN', { maximumFractionDigits: 3 }));

// Bộ mẫu để chạy thử trên tài liệu PayNhanh; bộ dữ liệu nghiên cứu phải do nhóm xây dựng và tách held-out.
const SAMPLE: EvalSet = { name: 'Bộ mẫu PayNhanh (chạy thử)', questions: [
  ['Hệ thống chống tạo hai đơn thanh toán khi khách bấm thanh toán nhiều lần như thế nào?', ['Idempotency-Key bắt buộc', 'Cùng key cùng nội dung trả lại đơn cũ', 'Cùng key khác nội dung trả lỗi 409', 'Hiệu lực trong 24 giờ']],
  ['Webhook được gửi lại tối đa bao nhiêu lần và merchant phải phản hồi trong bao lâu?', ['Gửi lại tối đa 8 lần', 'Khoảng cách tăng dần từ 1 phút đến 24 giờ', 'Merchant trả 2xx trong 10 giây']],
  ['Merchant kiểm tra chữ ký webhook như thế nào?', ['Dùng HMAC-SHA256', 'Ký dấu thời gian cộng thân yêu cầu nguyên văn', 'So sánh thời gian hằng định', 'Từ chối nếu lệch quá 5 phút']],
  ['Ai được duyệt yêu cầu hoàn tiền lớn và ngưỡng là bao nhiêu?', ['Từ 10.000.000 VND cần duyệt', 'Finance duyệt', 'Dưới ngưỡng xử lý tự động']],
  ['Thiết kế CSDL đảm bảo mỗi đơn chỉ có một giao dịch thành công bằng cách nào?', ['Chỉ mục duy nhất có điều kiện', 'one_success_per_payment', 'Giao dịch thứ hai đánh dấu REVERSED']],
  ['Mật khẩu merchant phải đáp ứng yêu cầu gì và khi nào tài khoản bị khóa?', ['Tối thiểu 12 ký tự', 'Kiểm tra danh sách mật khẩu đã lộ', 'Khóa 15 phút sau 5 lần sai liên tiếp']],
  ['Khi khách báo bị trừ tiền hai lần, nhóm vận hành xử lý theo các bước nào?', ['Tra cứu theo merchant_order_id', 'Kiểm tra số giao dịch SUCCEEDED', 'Kiểm tra Idempotency-Key của merchant', 'Phản hồi trong 4 giờ làm việc']],
  ['Mẫu outbox trong kiến trúc dùng để làm gì?', ['Ghi sự kiện cùng giao dịch cập nhật trạng thái', 'Tiến trình riêng đẩy sự kiện vào RabbitMQ', 'Không mất sự kiện khi trạng thái đã đổi']],
  ['Nhật ký kiểm toán được lưu bao lâu và bảo vệ thế nào?', ['Lưu tối thiểu 5 năm', 'Không cho phép sửa', 'Chuỗi băm phát hiện sửa đổi']],
  ['Thiết kế luồng hoàn tiền một phần an toàn cần những gì về CSDL, API và phân quyền?', ['Khóa dòng bằng SELECT FOR UPDATE', 'Tổng hoàn không vượt số đã thanh toán', 'API trả lỗi 422 REFUND_EXCEEDS_AMOUNT', 'Chỉ Merchant Owner được tạo hoàn tiền', 'Idempotency-Key bắt buộc']],
].map(([q, p], i) => ({ id: `Q${i + 1}`, question: q as string, points: p as string[] })) };

function shuffled<T>(items: T[], seedText: string): T[] {
  let seed = [...seedText].reduce((h, c) => (Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0), 2166136261);
  const rnd = () => { seed = (seed + 0x6d2b79f5) >>> 0; let t = seed; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const a = [...items];
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
const parseBulk = (text: string, start: number): Question[] => text.split('\n').map(l => l.trim()).filter(Boolean).map((line, i) => {
  const [q, p = ''] = line.split('||');
  return { id: `Q${start + i + 1}`, question: q.trim(), points: p.split(';').map(x => x.trim()).filter(Boolean) };
}).filter(q => q.question.length >= 5);

export const EvaluationView: React.FC<{ docs: Doc[] }> = ({ docs }) => {
  const sets = useAnalysisData('eval_set');
  const runs = useAnalysisData('evaluation');
  const [tab, setTab] = useState<'set' | 'run' | 'grade' | 'results'>('set');
  const [evalSet, setEvalSet] = useState<EvalSet>({ name: '', questions: [] });
  const [setId, setSetId] = useState<string | null>(null);
  const [bulk, setBulk] = useState('');
  const [scope, setScope] = useState<Set<string>>(new Set());
  const [conds, setConds] = useState<Set<string>>(new Set(['A', 'B', 'C']));
  const [repeats, setRepeats] = useState(1);
  const [run, setRun] = useState<RunState | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [grader, setGrader] = useState(() => { try { return localStorage.getItem('eval-grader') || ''; } catch { return ''; } });
  const [qIndex, setQIndex] = useState(0);
  const [unblind, setUnblind] = useState(false);
  const [stats, setStats] = useState<Record<string, { conditions: Record<string, Described>; comparisons: PairedComparison[] }>>({});
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const stop = useRef(false);
  const runRef = useRef<RunState | null>(null);
  runRef.current = run;
  const runIdRef = useRef<string | null>(null);  // mã báo cáo của lượt đang chạy; ref để không ghi nhầm vào lượt cũ
  const setRunIdBoth = (id: string | null) => { runIdRef.current = id; setRunId(id); };

  useEffect(() => { if (scope.size === 0 && docs.length) setScope(new Set(docs.map(docId))); }, [docs]);
  useEffect(() => { try { localStorage.setItem('eval-grader', grader); } catch { /* chế độ riêng tư */ } }, [grader]);
  const pickable = sets.allDocs.length ? sets.allDocs : docs;

  // ---------------- Bộ câu hỏi
  const updateQ = (i: number, patch: Partial<Question>) => setEvalSet(s => ({ ...s, questions: s.questions.map((q, n) => (n === i ? { ...q, ...patch } : q)) }));
  const renumber = (qs: Question[]) => qs.map((q, i) => ({ ...q, id: `Q${i + 1}` }));
  const saveSet = async () => {
    setError(null);
    const clean = { name: evalSet.name.trim() || 'Bộ câu hỏi chưa đặt tên', questions: renumber(evalSet.questions.filter(q => q.question.trim().length >= 5)) };
    if (!clean.questions.length) { setError('Bộ câu hỏi cần ít nhất một câu (từ 5 ký tự).'); return; }
    try {
      if (setId) await updateReport(setId, clean, clean.name); else setSetId((await saveReport({ kind: 'eval_set', title: clean.name, payload: clean })).report_id);
      setEvalSet(clean); await sets.refreshSaved(); setNote('Đã lưu bộ câu hỏi.');
    } catch (e: any) { setError(e.message); }
  };
  const loadSet = async (id: string) => { try { const r = await getReport(id); setEvalSet(r.payload); setSetId(id); setNote('Đã mở bộ câu hỏi.'); } catch (e: any) { setError(e.message); } };

  // ---------------- Chạy
  const plan = (st: RunState) => { const out: [Question, string, number][] = []; for (let r = 1; r <= st.repeats; r++) for (const q of st.set.questions) for (const c of st.conditions) out.push([q, c, r]); return out; };
  const persist = async (st: RunState) => {
    const title = `Đánh giá · ${st.set.name} · ${st.conditions.join('/')} · ${new Date(st.started).toLocaleString('vi-VN')}`;
    if (runIdRef.current) { await updateReport(runIdRef.current, st, title); return runIdRef.current; }
    const id = (await saveReport({ kind: 'evaluation', title, payload: st })).report_id; setRunIdBoth(id); await runs.refreshSaved(); return id;
  };
  const start = async (resume: boolean) => {
    setError(null); setNote(null);
    if (!evalSet.questions.length) { setError('Chưa có câu hỏi. Hãy soạn hoặc nạp bộ câu hỏi ở tab "Bộ câu hỏi".'); return; }
    const st: RunState = resume && run ? run : { set: { ...evalSet, questions: renumber(evalSet.questions) }, conditions: CONDITIONS.filter(c => conds.has(c)), repeats, sourceIds: [...scope], items: {}, grades: {}, started: new Date().toISOString() };
    if (!st.conditions.length) { setError('Chọn ít nhất một điều kiện.'); return; }
    if (!resume) setRunIdBoth(null);
    setRun(st); stop.current = false; setRunning(true);
    let done = 0;
    for (const [q, c, r] of plan(st)) {
      if (stop.current) break;
      const k = key(q.id, c, r);
      if (runRef.current?.items[k]?.status && !runRef.current.items[k].error) continue;
      let item: Item;
      try { item = { ...(await evalRun(q.question, c, st.sourceIds.length ? st.sourceIds : null, q.points)), qid: q.id, condition: c, repeat: r }; }
      catch (e: any) { item = { qid: q.id, condition: c, repeat: r, status: 'ERROR', error: e.message }; }
      setRun(prev => (prev ? { ...prev, items: { ...prev.items, [k]: item } } : prev));
      runRef.current = runRef.current ? { ...runRef.current, items: { ...runRef.current.items, [k]: item } } : runRef.current;
      if (++done % 5 === 0 && runRef.current) { try { await persist(runRef.current); } catch { /* lưu lại ở cuối */ } }
    }
    const final = runRef.current && { ...runRef.current, finished: stop.current ? undefined : new Date().toISOString() };
    setRunning(false);
    if (final) { setRun(final); try { await persist(final); setNote(stop.current ? 'Đã dừng và lưu phần đã chạy; bấm "Chạy tiếp" để hoàn tất.' : 'Đã chạy xong và lưu kết quả.'); } catch (e: any) { setError(e.message); } }
  };
  const loadRun = async (id: string) => {
    try { const st: RunState = (await getReport(id)).payload; setRun(st); setRunIdBoth(id); setEvalSet(st.set); setQIndex(0); setStats({}); setNote('Đã mở lượt đánh giá đã lưu.'); }
    catch (e: any) { setError(e.message); }
  };

  // ---------------- Chấm mù
  const questions = run?.set.questions ?? [];
  const current = questions[Math.min(qIndex, Math.max(0, questions.length - 1))];
  const answersFor = (qid: string) => run ? shuffled(Object.entries(run.items).filter(([, it]) => it.qid === qid && it.answer && !it.error && it.status !== 'FAILED'), `${run.started}|${qid}`) : [];
  const myGrades = run?.grades[grader.trim()] ?? {};
  const setScore = (k: string, c: keyof Score, v: number) => setRun(prev => {
    if (!prev || !grader.trim()) return prev;
    const g = prev.grades[grader.trim()] ?? {};
    return { ...prev, grades: { ...prev.grades, [grader.trim()]: { ...g, [k]: { ...(g[k] ?? { correct: 0, complete: 0, grounded: 0 }), [c]: v } } } };
  });
  const gradedQ = questions.filter(q => answersFor(q.id).every(([k]) => { const s = myGrades[k]; return s && s.correct && s.complete && s.grounded; }) && answersFor(q.id).length).length;
  const saveGrades = async () => { if (!run || !runId) return; try { await updateReport(runId, run); setNote('Đã lưu điểm chấm.'); } catch (e: any) { setError(e.message); } };

  // ---------------- Kết quả
  const items = run ? Object.values(run.items) : [];
  const humanScore = (k: string) => {
    // Lượt thất bại không có câu trả lời để chấm (và lộ phương pháp nếu hiện ra): khi đã có người chấm, tính 1 điểm.
    if (run?.items[k]?.status === 'FAILED') return Object.keys(run.grades).length ? 1 : null;
    const per = Object.values(run?.grades ?? {}).map(g => g[k]).filter(s => s && s.correct && s.complete && s.grounded) as Score[];
    return per.length ? avg(per.map(s => (s.correct + s.complete + s.grounded) / 3)) : null;
  };
  const tokens = (it: Item) => (it.metrics?.input_tokens ?? 0) + (it.metrics?.output_tokens ?? 0);
  const perQuestion = (metric: (k: string, it: Item) => number | null) => Object.fromEntries((run?.conditions ?? []).map(c => [c, questions.map(q => {
    const vals = Object.entries(run!.items).filter(([, it]) => it.qid === q.id && it.condition === c && !it.error).map(([k, it]) => metric(k, it)).filter(v => v != null) as number[];
    return avg(vals);
  })]));
  const METRICS: { id: string; label: string; fn: (k: string, it: Item) => number | null; better: 'higher' | 'lower'; d: number }[] = [
    { id: 'human', label: 'Điểm người chấm (1–5)', fn: k => humanScore(k), better: 'higher', d: 2 },
    { id: 'coverage', label: 'Độ phủ ý chính tự động (%)', fn: (_k, it) => (it.key_point_coverage == null ? null : it.key_point_coverage * 100), better: 'higher', d: 1 },
    { id: 'tokens', label: 'Token mỗi lượt', fn: (_k, it) => (it.metrics ? tokens(it) : null), better: 'lower', d: 0 },
    { id: 'latency', label: 'Độ trễ (giây)', fn: (_k, it) => (it.metrics?.latency_ms == null ? null : it.metrics.latency_ms / 1000), better: 'lower', d: 1 },
  ];
  const pairs = useMemo(() => { const cs = run?.conditions ?? []; return cs.includes('C') ? cs.filter(c => c !== 'C').map(c => ['C', c] as [string, string]) : cs.slice(1).map(c => [cs[0], c] as [string, string]); }, [run]);
  const computeStats = async () => {
    setError(null);
    try {
      const out: typeof stats = {};
      for (const m of METRICS) {
        const scores = perQuestion(m.fn);
        if (Object.values(scores).every(v => v.every(x => x == null))) continue;
        out[m.id] = await evalStats(scores, pairs);
      }
      setStats(out);
    } catch (e: any) { setError(e.message); }
  };
  useEffect(() => { if (tab === 'results' && run && items.length) void computeStats(); }, [tab, runId, items.length, JSON.stringify(run?.grades ?? {}).length]);

  const exportCsv = () => {
    if (!run) return;
    const head = ['Câu', 'Câu hỏi', 'Điều kiện', 'Lần', 'run_id', 'Trạng thái', 'Độ trễ (ms)', 'Token vào', 'Token ra', 'Số lần gọi mô hình', 'Trích dẫn hợp lệ', 'Độ phủ ý chính', 'Điểm người chấm TB', 'Số nhiệm vụ', 'config_hash'];
    const rows = Object.entries(run.items).map(([k, it]) => [it.qid, questions.find(q => q.id === it.qid)?.question, it.condition, it.repeat, it.run_id, it.error ? `LỖI: ${it.error}` : it.status,
      it.metrics?.latency_ms, it.metrics?.input_tokens, it.metrics?.output_tokens, it.metrics?.llm_calls, it.metrics?.citations_valid, it.key_point_coverage, humanScore(k), it.tasks, it.config_hash].map(csvCell).join(','));
    download(`danh-gia-${run.started.slice(0, 10)}.csv`, '﻿' + [head.map(csvCell).join(','), ...rows].join('\r\n'), 'text/csv;charset=utf-8');
  };

  const total = run ? plan(run).length : 0;
  const finished = items.filter(it => it.status && !it.error).length;
  const smallSample = questions.length < 10;

  return (
    <main className="pg tl tone-evaluation">
      <div className="pg-col tv-col">
        <ToolHeader Icon={ClipboardCheck} title="Phòng đánh giá" desc="Chạy cùng một bộ câu hỏi theo các điều kiện A/B/C, chấm mù và kiểm định thống kê để so sánh chất lượng, token và độ trễ."
          right={<SavedReportsSelect saved={runs.saved} onLoad={loadRun} disabled={running} />} />
        {error && <div className="note is-error" role="alert"><AlertCircle size={16} /><span>{error}</span><button className="note-x" onClick={() => setError(null)} aria-label="Đóng thông báo"><X size={14} /></button></div>}
        {note && <p className="muted-line" role="status"><CheckCircle2 size={14} />{note}</p>}

        {/* Bốn giai đoạn thành bốn thẻ lớn có số liệu; bấm thẻ để vào giai đoạn đó */}
        <div className="ev-stages" role="tablist" aria-label="Bước đánh giá">
          {([
            ['set', 'Bộ câu hỏi', ListOrdered, `${evalSet.questions.length}`, 'câu hỏi', evalSet.questions.length > 0],
            ['run', 'Chạy thực nghiệm', FlaskConical, total ? `${finished}/${total}` : `${evalSet.questions.length * conds.size * repeats}`, total ? 'lượt đã chạy' : 'lượt sẽ chạy', !!total && finished === total],
            ['grade', 'Chấm mù', EyeOff, questions.length ? `${gradedQ}/${questions.length}` : '—', grader.trim() ? `câu ${grader.trim()} đã chấm` : 'câu đã chấm', !!questions.length && gradedQ === questions.length],
            ['results', 'Kết quả', BarChart3, items.length ? `${run?.conditions.length ?? 0}` : '—', 'điều kiện so sánh', false],
          ] as [typeof tab, string, React.ComponentType<{ size?: number }>, string, string, boolean][]).map(([k, label, I, big, small, ok], n) => (
            <button key={k} role="tab" aria-selected={tab === k} className={`ev-stage${tab === k ? ' is-on' : ''}${ok ? ' is-ok' : ''}`} onClick={() => setTab(k)} disabled={(k === 'grade' || k === 'results') && !items.length}>
              <span className="ev-stage-top"><span className="ev-stage-n">{ok ? <CheckCircle2 size={15} /> : n + 1}</span><I size={18} /></span>
              <b>{big}</b><small>{small}</small><span className="ev-stage-l">{label}</span>
            </button>
          ))}
        </div>

        {tab === 'set' && <section className="tv-setup">
          <div className="ev-row">
            <label className="tv-field ev-grow"><span>Tên bộ câu hỏi</span><input className="ev-input" value={evalSet.name} onChange={e => setEvalSet(s => ({ ...s, name: e.target.value }))} placeholder="Ví dụ: Bộ đánh giá đợt 1 (held-out)" /></label>
            <SavedReportsSelect saved={sets.saved} onLoad={loadSet} />
          </div>
          <div className="ev-qs">{evalSet.questions.map((q, i) => (
            <div key={i} className="ev-q">
              <b>Q{i + 1}</b>
              <label className="tv-field"><span className="sr">Câu hỏi {i + 1}</span><textarea className="dz-input" rows={2} value={q.question} onChange={e => updateQ(i, { question: e.target.value })} placeholder="Câu hỏi" /></label>
              <label className="tv-field"><span className="sr">Ý chính của câu {i + 1}</span><textarea className="dz-input" rows={2} value={q.points.join('\n')} onChange={e => updateQ(i, { points: e.target.value.split('\n') })} placeholder="Ý chính cần có, mỗi dòng một ý" /></label>
              <button className="icon-btn is-sm" aria-label={`Xóa câu ${i + 1}`} onClick={() => setEvalSet(s => ({ ...s, questions: s.questions.filter((_, n) => n !== i) }))}><Trash2 size={14} /></button>
            </div>
          ))}</div>
          <div className="tv-actions">
            <button className="btn btn-ghost" onClick={() => setEvalSet(s => ({ ...s, questions: [...s.questions, { id: `Q${s.questions.length + 1}`, question: '', points: [] }] }))}><Plus size={15} />Thêm câu hỏi</button>
            <button className="btn btn-ghost" onClick={() => { setEvalSet(SAMPLE); setSetId(null); }}>Nạp bộ mẫu PayNhanh</button>
            <button className="btn btn-dark" onClick={saveSet}><Save size={15} />Lưu bộ câu hỏi</button>
          </div>
          <details className="tv-saved-list"><summary>Nhập nhanh nhiều câu</summary>
            <p className="muted-line">Mỗi dòng một câu theo dạng: <code>Câu hỏi || ý chính 1; ý chính 2</code></p>
            <textarea className="dz-input" rows={4} value={bulk} onChange={e => setBulk(e.target.value)} />
            <div className="tv-actions"><button className="btn btn-ghost" onClick={() => { setEvalSet(s => ({ ...s, questions: [...s.questions, ...parseBulk(bulk, s.questions.length)] })); setBulk(''); }} disabled={!bulk.trim()}>Thêm vào bộ</button></div>
          </details>
          <p className="muted-line">Bộ mẫu chỉ để chạy thử. Bộ dữ liệu nghiên cứu nên có ≥ 20 câu, ý chính do nhóm viết, tách riêng phần held-out và cố định trước khi chạy chính thức.</p>
        </section>}

        {tab === 'run' && <section className="tv-setup">
          <p className="muted-line"><FlaskConical size={15} />Bộ câu hỏi: <b>{(run?.set ?? evalSet).name || 'chưa đặt tên'}</b> · {(run?.set ?? evalSet).questions.length} câu</p>
          <fieldset className="tv-field" disabled={running}><legend>Điều kiện so sánh</legend>
            <div className="tv-docs">{CONDITIONS.map(c => (
              <label key={c} className={`chip${conds.has(c) ? ' is-on' : ''}`}><input type="checkbox" checked={conds.has(c)} onChange={e => setConds(prev => { const n = new Set(prev); e.target.checked ? n.add(c) : n.delete(c); return n; })} />{COND_VI[c]}</label>
            ))}</div>
          </fieldset>
          <label className="tv-field ev-narrow"><span>Số lần lặp mỗi cặp</span>
            <select value={repeats} onChange={e => setRepeats(Number(e.target.value))} disabled={running}>{[1, 2, 3].map(n => <option key={n} value={n}>{n}</option>)}</select></label>
          <DocPicker docs={pickable} selected={scope} onChange={setScope} disabled={running} legend="Tài liệu dùng để trả lời" />
          <div className="tv-actions">
            {running ? <button className="btn btn-danger" onClick={() => { stop.current = true; }}><Square size={14} />Dừng sau lượt này</button> : <>
              <button className="btn btn-dark" onClick={() => start(false)} disabled={!evalSet.questions.length}><FlaskConical size={15} />Chạy {evalSet.questions.length * conds.size * repeats} lượt mới</button>
              {run && finished < total && <button className="btn btn-ghost" onClick={() => start(true)}>Chạy tiếp {total - finished} lượt</button>}
            </>}
          </div>
          <p className="muted-line">Mọi điều kiện dùng cùng mô hình, cùng tài liệu và cùng thiết lập ngôn ngữ; mỗi lượt được lưu như một lượt nghiên cứu (xem ở Thực nghiệm → Nhật ký).</p>
          {run && <div className="tv-progress"><i style={{ width: `${total ? Math.round((finished / total) * 100) : 0}%` }} /><span>{running && <span className="spin is-dark" />}Đã chạy {finished}/{total} lượt{items.some(i => i.error) ? ` · ${items.filter(i => i.error).length} lỗi` : ''}</span></div>}
          {run && <div className="tbl"><table>
            <thead><tr><th>Câu</th>{run.conditions.map(c => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{run.set.questions.map(q => <tr key={q.id}><td title={q.question}><b>{q.id}</b> <small>{q.question.slice(0, 60)}{q.question.length > 60 ? '…' : ''}</small></td>
              {run.conditions.map(c => { const its = Array.from({ length: run.repeats }, (_, r) => run.items[key(q.id, c, r + 1)]).filter(Boolean) as Item[];
                if (!its.length) return <td key={c} className="is-muted">{running ? 'Chờ' : '—'}</td>;
                const ok = its.filter(i => !i.error);
                const cov = avg(ok.map(i => i.key_point_coverage).filter(v => v != null) as number[]);
                return <td key={c}><span className={`cht-status is-${ok.length === 0 ? 'failed' : ok.every(i => i.status === 'COMPLETE') ? 'complete' : ok.some(i => i.status === 'FAILED') ? 'failed' : 'partial'}`}>{ok.length === 0 ? 'Lỗi' : ok.map(i => i.status === 'COMPLETE' ? 'Đủ' : i.status === 'FAILED' ? 'Thất bại' : 'Một phần').join(' · ')}</span>
                  <small className="ev-cell">{num(avg(ok.map(i => (i.metrics?.latency_ms ?? 0) / 1000)))} giây · {num(avg(ok.map(tokens)), 0)} token{cov != null ? ` · phủ ${Math.round(cov * 100)}%` : ''}</small></td>; })}</tr>)}</tbody>
          </table></div>}
        </section>}

        {tab === 'grade' && run && current && <section className="tv-setup">
          <div className="ev-row">
            <label className="tv-field ev-grow"><span>Tên người chấm</span><input className="ev-input" value={grader} onChange={e => setGrader(e.target.value)} placeholder="Mỗi người chấm dùng một tên riêng" /></label>
            <label className="ev-toggle"><input type="checkbox" checked={unblind} onChange={e => setUnblind(e.target.checked)} /> Mở mù (hiện phương pháp)</label>
          </div>
          <div className="ev-nav">
            <button className="icon-btn" onClick={() => { void saveGrades(); setQIndex(i => Math.max(0, i - 1)); }} disabled={qIndex === 0} aria-label="Câu trước"><ChevronLeft size={18} /></button>
            <select value={qIndex} onChange={e => { void saveGrades(); setQIndex(Number(e.target.value)); }}>{questions.map((q, i) => <option key={q.id} value={i}>{q.id} · {q.question.slice(0, 50)}</option>)}</select>
            <button className="icon-btn" onClick={() => { void saveGrades(); setQIndex(i => Math.min(questions.length - 1, i + 1)); }} disabled={qIndex >= questions.length - 1} aria-label="Câu sau"><ChevronRight size={18} /></button>
            <span className="muted-line">Đã chấm đủ {gradedQ}/{questions.length} câu</span>
          </div>
          <div className="dz-card"><h3>{current.id}. {current.question}</h3>{current.points.length > 0 && <><b className="dz-sub">Ý chính tham chiếu</b><ul>{current.points.map((p, i) => <li key={i}>{p}</li>)}</ul></>}</div>
          {!grader.trim() && <p className="note is-error"><EyeOff size={15} />Nhập tên người chấm để bắt đầu chấm.</p>}
          {answersFor(current.id).map(([k, it], n) => (
            <article key={k} className="dz-card ev-answer">
              <header><h3>Câu trả lời {n + 1}{unblind && <small className="ev-cond"> · {COND_VI[it.condition]} · lần {it.repeat}</small>}</h3></header>
              <p className="ev-text">{it.answer}</p>
              <div className="ev-scores">{CRITERIA.map(([c, label]) => (
                <div key={c} role="radiogroup" aria-label={`${label} cho câu trả lời ${n + 1}`}><span>{label}</span>
                  {[1, 2, 3, 4, 5].map(v => <button key={v} role="radio" aria-checked={myGrades[k]?.[c] === v} className={myGrades[k]?.[c] === v ? 'is-on' : ''} disabled={!grader.trim()} onClick={() => setScore(k, c, v)}>{v}</button>)}
                </div>))}</div>
            </article>
          ))}
          {answersFor(current.id).length === 0 && <div className="empty">Câu này chưa có câu trả lời (lượt chạy lỗi hoặc chưa chạy).</div>}
          <div className="tv-actions is-end"><button className="btn btn-dark" onClick={saveGrades} disabled={!grader.trim() || !runId}><Save size={15} />Lưu điểm</button></div>
          <p className="muted-line">Thang 1–5: 1 = sai/thiếu hoàn toàn, 3 = đúng một phần, 5 = đúng, đủ, có căn cứ rõ. Người chấm không nên biết câu trả lời thuộc phương pháp nào cho tới khi chấm xong.</p>
        </section>}

        {tab === 'results' && run && <section className="ev-results">
          <div className="tbl"><table>
            <thead><tr><th>Điều kiện</th><th>Số lượt</th><th>Hoàn thành</th><th>Thất bại</th><th>Độ trễ TB</th><th>Token TB</th><th>Gọi mô hình TB</th><th>Độ phủ ý chính</th><th>Điểm người chấm</th></tr></thead>
            <tbody>{run.conditions.map(c => { const its = items.filter(i => i.condition === c && !i.error); const human = Object.entries(run.items).filter(([, i]) => i.condition === c).map(([k]) => humanScore(k)).filter(v => v != null) as number[];
              const cov = its.map(i => i.key_point_coverage).filter(v => v != null) as number[];
              return <tr key={c}><td><b>{COND_VI[c]}</b></td><td>{its.length}</td><td>{its.length ? `${Math.round((its.filter(i => i.status === 'COMPLETE').length / its.length) * 100)}%` : '—'}</td>
                <td>{its.filter(i => i.status === 'FAILED').length}</td><td>{num(avg(its.map(i => (i.metrics?.latency_ms ?? 0) / 1000)))} giây</td><td>{num(avg(its.map(tokens)), 0)}</td>
                <td>{num(avg(its.map(i => i.metrics?.llm_calls ?? 0)))}</td><td>{cov.length ? `${num(avg(cov)! * 100)}%` : 'Chưa đo'}</td><td>{human.length ? `${num(avg(human), 2)} (${human.length} lượt)` : 'Chưa chấm'}</td></tr>; })}</tbody>
          </table></div>
          {smallSample && <p className="note is-error"><AlertCircle size={15} />Mới có {questions.length} câu hỏi: cỡ mẫu nhỏ, kết quả kiểm định chỉ mang tính tham khảo. Bộ chính thức nên có ít nhất 20 câu.</p>}
          {METRICS.filter(m => stats[m.id]).map(m => (
            <article key={m.id} className="dz-card">
              <header><h3><BarChart3 size={16} />{m.label}</h3><small className="is-muted">{m.better === 'higher' ? 'cao hơn là tốt hơn' : 'thấp hơn là tốt hơn'} · ghép cặp theo câu hỏi</small></header>
              <div className="tbl"><table>
                <thead><tr><th>Điều kiện</th><th>n câu</th><th>Trung bình</th><th>Độ lệch chuẩn</th><th>Khoảng tin cậy 95%</th></tr></thead>
                <tbody>{Object.entries(stats[m.id].conditions).map(([c, d]) => <tr key={c}><td><b>{c}</b></td><td>{d.n}</td><td>{num(d.mean, m.d)}</td><td>{num(d.sd, m.d)}</td><td>{d.ci95 ? `${num(d.ci95[0], m.d)} – ${num(d.ci95[1], m.d)}` : '—'}</td></tr>)}</tbody>
              </table></div>
              {stats[m.id].comparisons.length > 0 && <div className="tbl"><table>
                <thead><tr><th>So sánh</th><th>Số cặp</th><th>Chênh lệch TB</th><th>p (Wilcoxon)</th><th>r rank-biserial</th><th>Cohen's dz</th><th>Đọc kết quả</th></tr></thead>
                <tbody>{stats[m.id].comparisons.map(cmp => { const p = cmp.wilcoxon.p_value; const better = cmp.mean_diff != null && (m.better === 'higher' ? cmp.mean_diff > 0 : cmp.mean_diff < 0);
                  return <tr key={cmp.a + cmp.b}><td><b>{cmp.a} so với {cmp.b}</b></td><td>{cmp.pairs}</td><td>{num(cmp.mean_diff, m.d)}</td><td>{pFmt(p)} <small className="is-muted">{cmp.wilcoxon.method}</small></td>
                    <td>{num(cmp.wilcoxon.rank_biserial, 2)}</td><td>{num(cmp.cohens_dz, 2)}</td>
                    <td><small>{p == null ? 'Không đủ cặp khác nhau' : p < 0.05 ? `Khác biệt có ý nghĩa ở mức 5%; ${cmp.a} ${better ? 'tốt hơn' : 'kém hơn'}` : 'Chưa thấy khác biệt có ý nghĩa'}</small></td></tr>; })}</tbody>
              </table></div>}
            </article>
          ))}
          <p className="muted-line">Độ phủ ý chính tự động chỉ so từ khóa nên là chỉ số phụ; kết luận chất lượng dựa trên điểm người chấm. Token và độ trễ đo thật từ mô hình cục bộ. Lượt thất bại không có câu trả lời: độ phủ tính 0%, điểm người chấm tính 1 và không đưa vào màn chấm mù.</p>
          <div className="tv-actions is-end">
            <button className="btn btn-ghost" onClick={exportCsv}><Download size={15} />Xuất CSV dữ liệu thô</button>
            <button className="btn btn-ghost" onClick={() => download(`danh-gia-${run.started.slice(0, 10)}.json`, JSON.stringify(run, null, 2), 'application/json')}><Download size={15} />Xuất JSON đầy đủ</button>
          </div>
        </section>}
      </div>
    </main>
  );
};
