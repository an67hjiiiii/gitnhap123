// Dựng nội dung hiển thị cho từng bước của lượt chạy CAP1 từ events[] thật (không suy ra số liệu mới).
// Không đưa mã kỹ thuật (T1, O2, SIMPLE_PROJECT_QUESTION...) ra giao diện: nhiệm vụ đánh số 1, 2, 3; nghĩa vụ hiện bằng mô tả.

export type StepState = 'done' | 'skip' | 'stop' | 'none';
type StepLike = { id: string; stepNumber: number; stages: string[] };
export type Tone = 'ok' | 'warn' | 'bad';
export type Task = { n: number; domain: string; goal: string; after: number[] };
export type Block =
  | { k: 'route'; simple: boolean; domains: string[] }
  | { k: 'quote'; label: string; text: string }
  | { k: 'checklist'; title: string; items: { text: string; ok?: boolean }[] }
  | { k: 'funnel'; found: number; used: number; dropped: number }
  | { k: 'docs'; ids: string[] }
  | { k: 'tasks'; tasks: Task[] }
  | { k: 'flow'; order: number[] }
  | { k: 'attempts'; items: { label: string; ok: boolean }[] }
  | { k: 'perTask'; rows: { n: number; domain: string; found: number; used: number; ids: string[]; limit?: number; need?: number }[] }
  | { k: 'answers'; items: { n: number; domain: string; status: string; cites: number; invalid: number; answer: string }[] }
  | { k: 'note'; tone: Tone; text: string };
export type StepView = { summary: string; stats: { value: number; label: string }[]; blocks: Block[] };

export const RUN_STATUS: Record<string, string> = { COMPLETE: 'Đủ bằng chứng', PARTIAL: 'Một phần', NO_EVIDENCE: 'Không có bằng chứng', FAILED: 'Thất bại' };
export const statusTone = (s?: string): Tone => (s === 'COMPLETE' ? 'ok' : s === 'FAILED' ? 'bad' : 'warn');
const REJECT_REASON: Record<string, string> = {
  task_plan_generation_failed: 'mô hình không tạo được kế hoạch đúng định dạng',
  task_plan_failed_verification_after_repair: 'kế hoạch vẫn thiếu việc phải làm sau một lần sửa',
  task_plan_verification_failed: 'kế hoạch không bao phủ đủ các việc bắt buộc',
  normalization_invalidated_task_plan: 'sau khi gộp việc trùng, kế hoạch không còn đủ các việc bắt buộc',
};
const PHASE: Record<string, string> = { initial: 'Kiểm tra lần đầu', post_repair: 'Kiểm tra sau khi sửa', post_normalization: 'Kiểm tra sau khi gộp việc trùng' };

const arr = (v: any): any[] => (Array.isArray(v) ? v : []);
const evts = (raw: any) => arr(raw?.events);
const route = (raw: any) => evts(raw).find(e => e.stage === 'product_request_routing')?.classification;
const isStop = (e: any) => ['planning_rejected', 'run_failed', 'run_budget_exceeded'].includes(e.stage) || e.status === 'FAILED';
// đường trả lời thẳng: pipeline không ghi task_completed, kết quả nằm ở task_results
const direct = (raw: any) => route(raw) === 'SIMPLE_PROJECT_QUESTION' || raw?.condition === 'A' || evts(raw).some(e => e.stage === 'product_help_response');

export function stepState(raw: any, step: StepLike): StepState {
  if (!raw) return 'none';
  const ev = evts(raw).filter(e => step.stages.includes(e.stage));
  if (ev.some(isStop)) return 'stop';
  if (ev.length) return 'done';
  if (step.id === 'step-7' && direct(raw) && arr(raw.task_results).length) return 'done';
  return 'skip';
}

export function skipReason(raw: any, step: StepLike, all: StepLike[]): string {
  const stopped = all.find(s => s.stepNumber < step.stepNumber && stepState(raw, s) === 'stop');
  if (stopped) return `Lượt chạy đã dừng ở bước ${stopped.stepNumber} nên không tới bước này.`;
  if (evts(raw).some(e => e.stage === 'product_help_response')) return 'Đây là câu hỏi về cách dùng hệ thống, đã có câu trả lời sẵn nên không cần bước này.';
  if (route(raw) === 'SIMPLE_PROJECT_QUESTION') return 'Câu hỏi đơn giản nên hệ thống đi đường tắt: tìm tài liệu rồi trả lời thẳng. Bước này chỉ dùng cho câu hỏi phức tạp cần lập kế hoạch.';
  if (raw?.condition === 'A') return 'Điều kiện A chỉ tìm tài liệu một lần rồi trả lời, không có bước này.';
  return 'Lượt chạy này không ghi lại hoạt động nào của bước này.';
}

/** Số thứ tự hiển thị của nhiệm vụ (T1 → 1) theo kế hoạch cuối cùng. */
function taskNumbers(raw: any): Map<string, number> {
  const plan = [...evts(raw)].reverse().find(e => ['validated_plan_handoff', 'normalization', 'decomposition'].includes(e.stage));
  const ids = arr(plan?.tasks).map(t => t.task_id).concat(arr(raw?.task_results).map(r => r.task_id));
  const m = new Map<string, number>();
  ids.forEach(id => { if (id && !m.has(id)) m.set(id, m.size + 1); });
  return m;
}
const toTasks = (list: any[], num: Map<string, number>): Task[] =>
  list.map(t => ({ n: num.get(t.task_id) ?? 0, domain: t.domain ?? '', goal: String(t.goal ?? ''), after: arr(t.depends_on).map(d => num.get(d) ?? 0).filter(Boolean) }));

export function stepView(raw: any, step: StepLike): StepView {
  const ev = evts(raw).filter(e => step.stages.includes(e.stage));
  const get = (s: string) => ev.filter(e => e.stage === s);
  const last = (s: string) => get(s).at(-1);
  const num = taskNumbers(raw);
  const blocks: Block[] = [];
  const stats: StepView['stats'] = [];
  let summary = '';
  const rejected = last('planning_rejected');

  switch (step.id) {
    case 'step-1': {
      const r = last('product_request_routing'), u = last('request_understanding'), fu = last('follow_up_resolved'), x = last('obligation_concern_extraction');
      if (last('product_help_response')) { summary = 'Đây là câu hỏi về cách dùng hệ thống, nên được trả lời ngay bằng hướng dẫn có sẵn.'; break; }
      if (r) blocks.push({ k: 'route', simple: r.classification === 'SIMPLE_PROJECT_QUESTION', domains: arr(r.detected_domains) });
      if (u) blocks.push({ k: 'quote', label: 'Câu hỏi hệ thống hiểu', text: u.normalized_request ?? u.request });
      if (fu) blocks.push({ k: 'quote', label: 'Hiểu tiếp theo câu hỏi trước (chỉ để hiểu ý, không phải nguồn)', text: fu.previous_request });
      if (x?.status === 'FAILED') blocks.push({ k: 'note', tone: 'bad', text: 'Mô hình không tách được các việc phải làm từ câu hỏi, nên lượt chạy dừng.' });
      else if (x) {
        stats.push({ value: arr(x.obligations).length, label: 'việc bắt buộc' }, { value: arr(x.concerns).length, label: 'mối quan tâm' });
        blocks.push({ k: 'checklist', title: 'Những việc câu trả lời phải làm được', items: arr(x.obligations).map(o => ({ text: o.description })) });
      }
      summary = r?.classification === 'SIMPLE_PROJECT_QUESTION' ? 'Hệ thống đọc câu hỏi, thấy nó đơn giản nên chọn đường tắt: tìm tài liệu rồi trả lời thẳng.'
        : x ? `Hệ thống đọc câu hỏi và tách ra ${arr(x.obligations).length} việc phải làm, dùng làm thước đo để kiểm tra kế hoạch ở bước 4.`
        : 'Hệ thống đọc và chuẩn hóa câu hỏi trước khi tìm tài liệu.';
      break;
    }
    case 'step-2': {
      const v = last('vanilla_retrieval'), p = last('planning_retrieval'), ks = last('knowledge_source_policy');
      if (ks) blocks.push({ k: 'note', tone: 'warn', text: ks.document_bound ? 'Chọn nguồn tri thức: câu hỏi gắn với tài liệu nên chỉ được trả lời từ tài liệu; tài liệu không có thì nói rõ là không có.'
        : ks.has_documents ? 'Chọn nguồn tri thức: dùng tài liệu trước; phần tài liệu không nói tới được trả lời bằng kiến thức chung và gắn nhãn riêng.'
        : 'Chọn nguồn tri thức: không có tài liệu nào trong phạm vi hỏi, các tác tử trả lời bằng kiến thức chung của mô hình (có nhãn, không có trích dẫn).' });
      if (v) {
        const found = arr(v.candidates).length, used = arr(v.selected).length, dropped = arr(v.dropped).length;
        stats.push({ value: found, label: 'đoạn tìm thấy' }, { value: used, label: 'đoạn được dùng' });
        blocks.push({ k: 'funnel', found, used, dropped });
        if (used) blocks.push({ k: 'docs', ids: arr(v.selected) });
        if (v.retrieval_fallback) blocks.push({ k: 'note', tone: 'warn', text: 'Cách tìm chính không trả kết quả, hệ thống đã chuyển sang tìm theo từ khóa.' });
        summary = used ? `Tìm trong tài liệu được ${found} đoạn liên quan, giữ ${used} đoạn tốt nhất để mô hình đọc.` : 'Không tìm thấy đoạn tài liệu nào đủ liên quan đến câu hỏi.';
      } else if (p) {
        const used = arr(p.selected).length;
        if (p.enabled === false) { summary = 'Điều kiện này tắt bước tìm tài liệu cho kế hoạch.'; break; }
        stats.push({ value: used, label: 'đoạn tham khảo' });
        if (used) blocks.push({ k: 'docs', ids: arr(p.selected) });
        summary = used ? `Chọn ${used} đoạn tài liệu để kế hoạch bám theo nội dung thật, không dựa vào hiểu biết chung của mô hình.` : 'Không thấy đoạn nào đủ liên quan; kế hoạch được lập không có tài liệu tham khảo.';
      }
      break;
    }
    case 'step-3': {
      const g = last('planning_generation'), d = last('decomposition');
      const tasks = toTasks(arr(d?.tasks), num);
      if (tasks.length) blocks.push({ k: 'tasks', tasks });
      if (g?.repair_attempted) blocks.push({ k: 'note', tone: 'warn', text: 'Lần đầu mô hình viết sai định dạng, hệ thống đã yêu cầu viết lại một lần.' });
      const n = tasks.length || arr(g?.task_ids).length;
      if (n) stats.push({ value: n, label: 'nhiệm vụ' }, { value: new Set(tasks.map(t => t.domain)).size, label: 'vai trò' });
      summary = n ? `Chia câu hỏi thành ${n} nhiệm vụ nhỏ, mỗi nhiệm vụ giao cho một tác tử theo chuyên môn.` : 'Mô hình không lập được kế hoạch.';
      break;
    }
    case 'step-4': {
      const descOf = new Map(arr(evts(raw).find(e => e.stage === 'obligation_concern_extraction')?.obligations).map((o: any) => [o.obligation_id, o.description]));
      const attempts = ev.filter(e => ['plan_verification', 'planning_repair', 'plan_anchoring'].includes(e.stage)).map(e => ({
        label: e.stage === 'plan_verification' ? (PHASE[e.phase] ?? 'Kiểm tra') : e.stage === 'planning_repair' ? (e.phase === 'parse' ? 'Mô hình viết lại định dạng' : 'Mô hình sửa kế hoạch') : 'Hệ thống tự bổ sung việc còn thiếu',
        ok: Boolean(e.stage === 'plan_verification' ? e.valid : e.accepted),
      }));
      if (attempts.length) blocks.push({ k: 'attempts', items: attempts });
      const lastCheck = [...get('plan_verification')].reverse().find(e => arr(e.covered_obligations).length || arr(e.missing_required_obligations).length);
      if (lastCheck) blocks.push({ k: 'checklist', title: 'Đối chiếu với các việc phải làm', items: [
        ...arr(lastCheck.covered_obligations).map(id => ({ text: descOf.get(id) ?? 'Một việc bắt buộc', ok: true })),
        ...arr(lastCheck.missing_required_obligations).map(id => ({ text: descOf.get(id) ?? 'Một việc bắt buộc', ok: false })),
      ] });
      if (rejected) blocks.push({ k: 'note', tone: 'bad', text: `Kế hoạch bị từ chối vì ${REJECT_REASON[rejected.reason] ?? 'không đạt kiểm tra'}. Hệ thống dừng ở đây để không tốn công trả lời theo một kế hoạch sai.` });
      stats.push({ value: get('plan_verification').length, label: 'lần kiểm tra' }, { value: get('planning_repair').length + get('plan_anchoring').length, label: 'lần sửa' });
      summary = rejected ? 'Kế hoạch không đạt sau các lần sửa, nên hệ thống dừng lại.'
        : attempts.length && attempts.every(a => a.ok) ? 'Kế hoạch đạt ngay lần kiểm tra đầu: đủ mọi việc phải làm, giao đúng vai trò.'
        : 'Kế hoạch lúc đầu còn thiếu, đã được sửa và đạt yêu cầu.';
      break;
    }
    case 'step-5': {
      const nm = last('normalization'), h = last('validated_plan_handoff');
      const order = arr(h?.execution_order).map(id => num.get(id) ?? 0).filter(Boolean);
      if (nm) stats.push({ value: nm.removed ?? 0, label: 'việc trùng đã gộp' });
      if (h) stats.push({ value: arr(h.tasks).length, label: 'nhiệm vụ chốt' });
      if (order.length) blocks.push({ k: 'flow', order });
      if (h) blocks.push({ k: 'tasks', tasks: toTasks(arr(h.tasks), num) });
      summary = nm?.removed ? `Gộp ${nm.removed} nhiệm vụ trùng nhau, chốt ${arr(h?.tasks).length} nhiệm vụ và thứ tự chạy.` : `Không có nhiệm vụ trùng; chốt ${arr(h?.tasks).length} nhiệm vụ và thứ tự chạy.`;
      break;
    }
    case 'step-6': {
      const b = last('adaptive_budget_plan');
      const rows = get('task_retrieval').map(e => ({ n: num.get(e.task_id) ?? 0, domain: '', found: arr(e.candidates).length, used: arr(e.selected).length, ids: arr(e.selected),
        limit: b?.limits?.[e.task_id], need: b?.needs?.[e.task_id] }));
      const plan = [...evts(raw)].reverse().find(e => e.stage === 'validated_plan_handoff');
      rows.forEach(r => { r.domain = arr(plan?.tasks).find(t => num.get(t.task_id) === r.n)?.domain ?? ''; });
      if (rows.length) blocks.push({ k: 'perTask', rows });
      const used = rows.reduce((s, r) => s + r.used, 0);
      stats.push({ value: rows.length, label: 'nhiệm vụ tự tìm' }, { value: used, label: 'đoạn được dùng' });
      summary = `Mỗi nhiệm vụ tự tìm tài liệu của riêng mình${b ? ' và được chia một phần ngân sách token theo nhu cầu' : ''}, tổng cộng ${used} đoạn được đưa cho các tác tử.`;
      break;
    }
    case 'step-7': {
      const results = get('task_completed').length ? get('task_completed').map(e => e.result ?? {}) : arr(raw?.task_results);
      const general = get('knowledge_source').filter(e => e.source === 'general').length;
      if (general) blocks.push({ k: 'note', tone: 'warn', text: `${general} phần được trả lời bằng kiến thức chung của mô hình, không từ tài liệu: nên kiểm tra lại với nguồn tin cậy.` });
      const items = results.map((r: any) => ({ n: num.get(r.task_id) ?? 0, domain: r.domain ?? '', status: r.status, cites: arr(r.citations).length, invalid: arr(r.invalid_citations).length, answer: String(r.answer ?? '') }));
      if (items.length) blocks.push({ k: 'answers', items });
      const over = last('run_budget_exceeded');
      if (over) blocks.push({ k: 'note', tone: 'bad', text: `Lượt chạy đã dùng ${over.total_tokens} token, vượt trần cho phép nên dừng các nhiệm vụ còn lại.` });
      stats.push({ value: items.length, label: direct(raw) ? 'lượt trả lời' : 'tác tử đã trả lời' }, { value: items.filter(i => i.status === 'COMPLETE').length, label: 'đủ bằng chứng' });
      summary = direct(raw) ? 'Mô hình đọc các đoạn đã chọn và trả lời trực tiếp trong một lượt, không cần chia cho nhiều tác tử.'
        : `${items.length} tác tử lần lượt trả lời phần việc của mình, chỉ được trích các đoạn tài liệu đã giao.`;
      break;
    }
    case 'step-8': {
      const f = last('run_finished'), x = last('run_failed');
      if (x) { blocks.push({ k: 'note', tone: 'bad', text: 'Lượt chạy gặp lỗi kỹ thuật và không tạo được câu trả lời.' }); summary = 'Lượt chạy thất bại.'; break; }
      if (f) blocks.push({ k: 'note', tone: statusTone(f.status), text: `Trạng thái cuối: ${RUN_STATUS[f.status] ?? f.status}. ${evts(raw).some(e => e.stage === 'knowledge_source' && e.source === 'general') ? 'Có phần trả lời bằng kiến thức chung (đã gắn nhãn), không từ tài liệu.' : f.status === 'COMPLETE' ? 'Mọi phần của câu trả lời đều có đoạn tài liệu làm căn cứ.' : f.status === 'PARTIAL' ? 'Một số phần chưa tìm được căn cứ trong tài liệu.' : f.status === 'NO_EVIDENCE' ? 'Tài liệu không có thông tin để trả lời.' : ''}` });
      if (raw?.answer) blocks.push({ k: 'quote', label: 'Câu trả lời cuối', text: String(raw.answer) });
      summary = direct(raw) ? 'Câu trả lời được kiểm tra trích dẫn rồi gửi cho bạn.' : 'Gộp phần trả lời của các tác tử thành một câu trả lời hoàn chỉnh, kèm trạng thái mức độ có căn cứ.';
      break;
    }
  }
  return { summary, stats: stats.filter(s => Number.isFinite(s.value)), blocks };
}
