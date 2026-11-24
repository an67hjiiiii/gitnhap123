import test from 'node:test';
import assert from 'node:assert/strict';
import { LiveDirector, LivePacer, characterFor, replayPlan } from '../src/studio/office3d/liveDirector.ts';

function fakeController() {
  const calls = [];
  const rec = (name) => (...args) => calls.push([name, ...args]);
  return { calls, resetToSleep: rec('reset'), wakeAgents: rec('wake'), putAgentsToSleep: rec('sleep'), setAgentAction: rec('act'), setLiveScene: rec('scene') };
}
const woken = (calls) => calls.filter(c => c[0] === 'wake').flatMap(c => c[1]);

test('câu đơn giản: chỉ Orchestrator, RAG, Integrator thức; các Agent khác ngủ', () => {
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('Nghỉ phép năm bao nhiêu ngày?');
  for (const e of [
    { type: 'progress', stage: 'agent_selection', agents: ['general'] },
    { type: 'progress', stage: 'product_request_routing', classification: 'SIMPLE_PROJECT_QUESTION' },
    { type: 'progress', stage: 'vanilla_retrieval' },
    { type: 'answer', text: 'Mười hai' },
    { type: 'progress', stage: 'run_finished' },
  ]) d.handle(e);
  assert.deepEqual(new Set(woken(c.calls)), new Set(['orchestrator', 'rag', 'integrator']));
  assert.ok(st.finished && !st.failed);
  assert.deepEqual(st.awake, ['integrator']);  // còn Integrator cầm câu trả lời, còn lại về ngủ
  assert.ok(st.steps.every(s => s.state === 'done'));
});

test('câu nhiều ý: chuyên gia thức đúng lúc việc của mình bắt đầu, theo thứ tự máy chủ báo', () => {
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('Thử việc có được nghỉ phép không, ngân sách quảng cáo tăng bao nhiêu?');
  d.handle({ type: 'progress', stage: 'agent_selection', agents: ['hr', 'finance', 'general'] });
  assert.ok(!woken(c.calls).includes('hr'), 'chưa giao việc thì chưa thức');
  d.handle({ type: 'progress', stage: 'planning_generation' });
  d.handle({ type: 'progress', stage: 'plan_verification' });
  d.handle({ type: 'progress', stage: 'task_started', task_id: 'T1', domain: 'hr' });
  d.handle({ type: 'progress', stage: 'task_retrieval', task_id: 'T1', domain: 'hr' });
  d.handle({ type: 'progress', stage: 'task_completed', task_id: 'T1', domain: 'hr' });
  d.handle({ type: 'progress', stage: 'task_started', task_id: 'T2', domain: 'finance' });
  d.handle({ type: 'progress', stage: 'task_completed', task_id: 'T2' });  // thiếu domain: nhớ từ lúc bắt đầu
  d.handle({ type: 'progress', stage: 'synthesis_started' });
  d.handle({ type: 'progress', stage: 'run_finished' });
  const order = woken(c.calls);
  assert.ok(order.indexOf('hr') < order.indexOf('finance'));
  assert.ok(!order.includes('marketing') && !order.includes('software'));
  const done = c.calls.filter(x => x[0] === 'act' && x[2] === 'completed' && x[1] !== 'reviewer').map(x => x[1]);
  assert.ok(c.calls.some(x => x[0] === 'act' && x[1] === 'reviewer' && x[3] === 'Kế hoạch đã qua kiểm tra'), 'giao việc thì Reviewer rời bảng về bàn');
  assert.deepEqual(done.slice(0, 2), ['hr', 'finance']);
  assert.equal(st.steps.find(s => s.key === 'task-T1').state, 'done');
});

test('kế hoạch bị từ chối: đánh dấu lỗi, không vẽ thành công', () => {
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('x');
  d.handle({ stage: 'plan_verification' });
  d.handle({ stage: 'planning_rejected' });
  d.handle({ stage: 'run_failed' });
  assert.ok(st.finished && st.failed);
  assert.ok(st.steps.some(s => s.state === 'fail'));
  assert.ok(!c.calls.some(x => x[0] === 'scene' && x[1]?.effects?.finalReportReady));
});

test('Chuyên viên tổng hợp ngồi bàn Integrator; tác tử chưa có bàn riêng ngồi bàn RAG; Số liệu ở bàn Data Analyst', () => {
  assert.equal(characterFor('conditions'), 'rag');
  assert.equal(characterFor('general'), 'integrator');
  assert.equal(characterFor('figures'), 'analyst');
  assert.equal(characterFor('hr'), 'hr');
  assert.equal(characterFor('database'), 'software');
});

test('xem lại: độ trễ theo mốc thời gian thật, chặn khoảng quá dài', () => {
  const plan = replayPlan([
    { stage: 'agent_selection', ts: '2026-11-23T10:00:00.000Z' },
    { stage: 'task_started', ts: '2026-11-23T10:00:01.500Z' },
    { stage: 'task_completed', ts: '2026-11-23T10:00:30.000Z' },
    { note: 'không có stage' },
  ], 6000);
  assert.deepEqual(plan.map(p => p.delayMs), [0, 1500, 6000]);
  assert.equal(plan[2].realGapMs, 28500);  // khoảng chờ thật vẫn giữ để hiện đúng số giây
});

test('song song thật: nhiều chuyên gia cùng đang làm, mỗi việc xong riêng', () => {
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('3 ý độc lập');
  d.handle({ stage: 'parallel_execution', limit: 2, waves: [['T1', 'T2']] });
  assert.match(st.headline, /cùng lúc 2 việc/);
  d.handle({ stage: 'task_started', task_id: 'T1', domain: 'hr' });
  d.handle({ stage: 'task_started', task_id: 'T2', domain: 'finance' });
  assert.deepEqual(st.steps.filter(s => s.state === 'now').map(s => s.key), ['task-T1', 'task-T2']);
  d.handle({ stage: 'task_completed', task_id: 'T2' });
  assert.equal(st.steps.find(s => s.key === 'task-T2').state, 'done');
  assert.equal(st.steps.find(s => s.key === 'task-T1').state, 'now');
});

test('chọn nguồn tri thức: Orchestrator có bước riêng, chuyên gia trả lời bằng kiến thức chung khi không có tài liệu', () => {
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('So sánh SQL và NoSQL');
  d.handle({ type: 'progress', stage: 'agent_selection', agents: ['software', 'general'] });
  d.handle({ type: 'progress', stage: 'knowledge_source_policy', has_documents: false, document_bound: false });
  d.handle({ type: 'progress', stage: 'task_started', task_id: 'T1', domain: 'software' });
  d.handle({ type: 'progress', stage: 'knowledge_source', task_id: 'T1', domain: 'software', source: 'general' });
  d.handle({ type: 'progress', stage: 'run_finished' });
  assert.ok(st.steps.some(s => s.key === 'source' && s.actor === 'orchestrator'));
  assert.ok(c.calls.some(x => x[0] === 'act' && x[1] === 'software' && String(x[3]).includes('kiến thức chung')));
});

// Đợt 1 (23/11): luồng trực tiếp gửi bản rút gọn của run.events (giống brief trong pipeline.event()).
const BRIEF = ['task_id', 'domain', 'classification', 'agents', 'has_documents', 'document_bound', 'source', 'review_status', 'waves', 'limit'];
function toLive(e) {
  const b = { type: 'progress', stage: e.stage };
  for (const k of BRIEF) if (k in e) b[k] = e[k];
  if (Array.isArray(e.unsupported)) b.unsupported = e.unsupported.length;
  if (e.result?.task_id) {
    b.task_id = e.result.task_id;
    b.result = Object.fromEntries(['task_id', 'domain', 'status'].filter(k => e.result[k]).map(k => [k, e.result[k]]));
    if (e.result.domain) b.domain = e.result.domain;
  }
  return b;
}
function play(events) {
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('Câu hỏi');
  events.forEach(e => d.handle(e));
  return { st, acts: c.calls.filter(x => x[0] === 'act').map(x => `${x[1]}|${x[2]}|${x[3]}`) };
}

test('Trực tiếp và Xem lại cho cùng trạng thái cuối với cùng một lượt chạy', () => {
  const saved = [
    { stage: 'agent_selection', agents: ['hr', 'finance', 'general'], ts: '2026-11-23T10:00:00Z' },
    { stage: 'knowledge_source_policy', has_documents: true, document_bound: false },
    { stage: 'planning_generation' },
    { stage: 'plan_verification', valid: true },
    { stage: 'parallel_execution', limit: 2, waves: [['T1', 'T2']] },
    { stage: 'task_started', task_id: 'T1', domain: 'hr' },
    { stage: 'task_started', task_id: 'T2', domain: 'finance' },
    { stage: 'knowledge_source', task_id: 'T2', domain: 'finance', source: 'general', evidence_chunks: 0 },
    { stage: 'task_completed', result: { task_id: 'T1', domain: 'hr', status: 'COMPLETE', answer: 'nội dung', citations: ['c1'] } },
    { stage: 'task_completed', result: { task_id: 'T2', domain: 'finance', status: 'NO_EVIDENCE', answer: '' } },
    { stage: 'synthesis_started', task_count: 2 },
    { stage: 'review_started' },
    { stage: 'review_finished', review_status: 'ok', checked: 3, unsupported: ['ý A', 'ý B'] },
    { stage: 'run_finished', status: 'PARTIAL' },
  ];
  const live = saved.map(toLive);
  live.splice(live.findIndex(e => e.stage === 'synthesis_started') + 1, 0, { type: 'answer', text: 'chữ đầu' });
  const a = play(saved);
  const b = play(live);
  assert.deepEqual(b.st, a.st);
  assert.deepEqual(b.acts, a.acts);  // Đợt 2: chữ đầu tiên sau bước tổng hợp không thêm hành động nào
  // những trạng thái từng bị sai ở Trực tiếp
  assert.ok(b.acts.some(x => x.startsWith('orchestrator|thinking|Nguồn: tài liệu, thiếu thì')));
  assert.ok(b.acts.some(x => x.startsWith('finance|working_computer|') && x.includes('kiến thức chung')));
  assert.equal(b.st.steps.find(s => s.key === 'task-T2').state, 'fail');
  assert.ok(b.acts.includes('reviewer|completed|2 ý chưa thấy trong tài liệu'));
  assert.match(JSON.stringify(b.acts), /Giao việc|cùng lúc 2 việc/);
});

// Đợt 2 (23/11): đúng người làm.
test('không có tài liệu: RAG ngủ suốt lượt, Orchestrator báo trả lời bằng kiến thức chung', () => {
  const saved = [
    { stage: 'agent_selection', agents: ['general'] },
    { stage: 'product_request_routing', classification: 'SIMPLE_PROJECT_QUESTION' },
    { stage: 'knowledge_source_policy', has_documents: false, document_bound: false },
    { stage: 'vanilla_retrieval', candidates: [] },
    { stage: 'knowledge_source', task_id: 'T1', domain: 'general', source: 'general', evidence_chunks: 0 },
    { stage: 'run_finished' },
  ];
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('Thủ đô của Úc?');
  saved.forEach(e => d.handle(e));
  assert.ok(!woken(c.calls).includes('rag'));
  assert.ok(c.calls.some(x => x[0] === 'act' && x[1] === 'orchestrator' && String(x[3]).includes('kiến thức chung')));
  assert.ok(c.calls.some(x => x[0] === 'act' && x[1] === 'integrator' && String(x[3]).includes('Chuyên viên tổng hợp trả lời bằng kiến thức chung')));
  assert.ok(!st.steps.some(s => s.actor === 'rag'));
});

test('không có tài liệu, câu nhiều việc: tìm tài liệu cho từng việc không chen dòng trạng thái của chuyên gia', () => {
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('x');
  d.handle({ stage: 'knowledge_source_policy', has_documents: false, document_bound: false });
  d.handle({ stage: 'task_started', task_id: 'T1', domain: 'hr' });
  d.handle({ stage: 'task_retrieval', task_id: 'T1', domain: 'hr' });
  assert.match(st.headline, /Chuyên gia Nhân sự/);
  assert.ok(!woken(c.calls).includes('rag'));
});

test('câu nhiều việc: chữ đầu tiên trước bước tổng hợp không đánh thức Integrator', () => {
  const c = fakeController();
  const d = new LiveDirector(c, () => {});
  d.start('x');
  d.handle({ type: 'progress', stage: 'product_request_routing', classification: 'COMPLEX_PROJECT_REQUEST' });
  d.handle({ type: 'answer', text: 'sớm' });
  assert.ok(!woken(c.calls).includes('integrator'));
  d.handle({ type: 'progress', stage: 'synthesis_started' });
  d.handle({ type: 'answer', text: 'chữ đầu' });
  assert.equal(c.calls.filter(x => x[0] === 'act' && x[1] === 'integrator').length, 1);  // chỉ "Tổng hợp câu trả lời"
});

test('câu đơn giản có tài liệu: Trực tiếp và Xem lại cho cùng trạng thái cuối, Chuyên viên tổng hợp viết ở bàn Integrator', () => {
  const saved = [
    { stage: 'agent_selection', agents: ['general'] },
    { stage: 'product_request_routing', classification: 'SIMPLE_PROJECT_QUESTION' },
    { stage: 'knowledge_source_policy', has_documents: true, document_bound: true },
    { stage: 'vanilla_retrieval', candidates: ['c1'] },
    { stage: 'knowledge_source', task_id: 'T1', domain: 'general', source: 'documents', evidence_chunks: 1 },
    { stage: 'run_finished' },
  ];
  const live = saved.map(toLive);
  live.splice(4, 0, { type: 'answer', text: 'Mười hai' });
  const a = play(saved);
  const b = play(live);
  assert.deepEqual(b.st, a.st);
  assert.ok(a.st.steps.some(s => s.key === 'write' && s.actor === 'integrator'));
  assert.ok(a.acts.some(x => x.startsWith('integrator|integrating|Chuyên viên tổng hợp viết câu trả lời từ tài liệu')));
});

// Đợt 3 (23/11): đúng nhịp. Đồng hồ giả để test không phải chờ thật.
function fakeClock() {
  let t = 0; let id = 0; const timers = new Map();
  return {
    now: () => t,
    setTimeout: (fn, ms) => { timers.set(++id, { at: t + ms, fn }); return id; },
    clearTimeout: (i) => { timers.delete(i); },
    advance(ms) {
      const end = t + ms;
      for (;;) {
        const due = [...timers.entries()].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]); t = due[1].at; due[1].fn();
      }
      t = end;
    },
  };
}

test('nhịp: mỗi bước hiện tối thiểu 700 ms, sự kiện dồn thì gộp, trạng thái cuối như áp thẳng', () => {
  const clock = fakeClock();
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('Nghỉ phép năm bao nhiêu ngày?');
  const pacer = new LivePacer(d, { clock });
  const events = [
    { type: 'progress', stage: 'agent_selection', agents: ['general'] },
    { type: 'progress', stage: 'product_request_routing', classification: 'SIMPLE_PROJECT_QUESTION' },
  ];
  events.forEach(e => pacer.push(e));
  clock.advance(0);
  assert.equal(st.steps.length, 2, 'bước đầu áp ngay');  // nhận + chọn chuyên gia
  clock.advance(300);
  assert.equal(st.headline.includes('Câu đơn giản'), false, 'chưa đủ 700 ms thì chưa sang bước sau');
  clock.advance(400);
  assert.ok(st.headline.includes('Câu đơn giản'));
  // dồn 4 sự kiện trong một lúc: gộp, không diễn từng bước
  const rest = [
    { type: 'progress', stage: 'knowledge_source_policy', has_documents: true, document_bound: true },
    { type: 'progress', stage: 'vanilla_retrieval' },
    { type: 'answer', text: 'Mười hai' },
    { type: 'progress', stage: 'knowledge_source', task_id: 'T1', domain: 'general', source: 'documents' },
    { type: 'progress', stage: 'run_finished' },
  ];
  rest.forEach(e => pacer.push(e));
  clock.advance(700);
  assert.ok(st.finished, 'gộp xong trong một nhịp');
  const ref = play([...events, ...rest]);
  assert.deepEqual(st, { ...ref.st, question: st.question });
  pacer.dispose();
});

test('im quá 1,5 giây: người đang giữ việc báo chờ mô hình kèm số giây, đứng yên tại chỗ', () => {
  const clock = fakeClock();
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('x');
  const pacer = new LivePacer(d, { clock });
  pacer.push({ type: 'progress', stage: 'planning_generation' });
  clock.advance(1000);
  assert.equal(st.waitingSec, null);
  clock.advance(2000);
  assert.equal(st.waitingSec, 3);
  const last = c.calls.filter(x => x[0] === 'act').at(-1);
  assert.deepEqual(last.slice(1, 3), ['orchestrator', 'planning_board'], 'giữ nguyên hành động đang làm, chỉ đổi dòng chữ');
  assert.match(last[3], /chờ mô hình · 3 giây/);
  assert.equal(last[5], 'whiteboard', 'không đi về bàn giữa lúc lập kế hoạch');
  const n = c.calls.length;
  clock.advance(500);
  assert.equal(c.calls.length, n, 'cùng một giây thì không gọi robot lại');
  clock.advance(500);
  assert.equal(st.waitingSec, 4);
  pacer.push({ type: 'progress', stage: 'plan_verification' });
  clock.advance(0);
  assert.equal(st.waitingSec, null, 'có sự kiện mới thì hết chờ');
  pacer.dispose();
});

test('xem lại: khoảng chờ thật đã lưu hiện đúng số giây, không đo bằng thời gian diễn', () => {
  const clock = fakeClock();
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('x');
  const pacer = new LivePacer(d, { clock, trackIdle: false });
  pacer.push({ stage: 'synthesis_started' });
  pacer.pushWait(14);
  clock.advance(700);
  assert.equal(st.waitingSec, 14);
  assert.ok(c.calls.some(x => x[0] === 'act' && x[1] === 'integrator' && x[3] === 'Lúc chạy thật chờ mô hình 14 giây'));
  pacer.push({ stage: 'synthesis_finished' });  // sự kiện văn phòng không diễn: vẫn đang chờ
  clock.advance(700);
  assert.equal(st.waitingSec, 14);
  pacer.dispose();
});

// Mục 3 kịch bản kiểm tra (23/11): mỗi sự kiện thật gây ra một hành động nhìn thấy được.
const acts = (c, who) => c.calls.filter(x => x[0] === 'act' && x[1] === who);
const scenes = (c) => c.calls.filter(x => x[0] === 'scene').map(x => x[1]);

test('lập kế hoạch: số thẻ trên bảng bằng số việc con thật; Reviewer ra bảng soát với giấy', () => {
  const c = fakeController();
  const d = new LiveDirector(c, () => {});
  d.start('x');
  d.handle({ stage: 'planning_generation' });
  assert.equal(scenes(c).at(-1).effects.whiteboardCards, 1, 'thẻ nháp khi chưa biết số việc');
  d.handle({ stage: 'plan_verification' });
  const rv = acts(c, 'reviewer').at(-1);
  assert.equal(rv[2], 'reviewing_paper'); assert.equal(rv[4], 'approved_sheet'); assert.equal(rv[5], 'board_review');
  d.handle({ stage: 'decomposition', task_count: 3 });
  assert.equal(scenes(c).at(-1).effects.whiteboardCards, 3);
});

test('tìm tài liệu: gói tài liệu bay từ RAG tới đúng người cần; không có đoạn nào thì không mở tủ', () => {
  const c = fakeController();
  const d = new LiveDirector(c, () => {});
  d.start('x');
  d.handle({ stage: 'knowledge_source_policy', has_documents: true });
  d.handle({ stage: 'task_started', task_id: 'T1', domain: 'marketing' });
  d.handle({ stage: 'task_retrieval', task_id: 'T1', domain: 'marketing', selected_count: 4 });
  assert.deepEqual(scenes(c).at(-1).dispatch, { from: 'rag', toList: ['marketing'] });  // Thời gian thật (mặc định): gói bay
  assert.equal(scenes(c).at(-2).effects.cabinetOpen, true);
  assert.match(acts(c, 'rag').at(-1)[3], /4 đoạn/);
  const c2 = fakeController();
  const d2 = new LiveDirector(c2, () => {});
  d2.start('Thủ đô của Úc?');
  d2.handle({ stage: 'knowledge_source_policy', has_documents: true });
  d2.handle({ stage: 'vanilla_retrieval', selected_count: 0 });
  assert.equal(scenes(c2).at(-1).effects.cabinetOpen, false);
  assert.ok(!scenes(c2).some(s => s.dispatch?.from === 'rag'));
  assert.ok(!acts(c2, 'rag').some(x => x[5] === 'cabinet'), 'không đi tới tủ hồ sơ');
});

test('song song: cả hai chuyên gia đang làm cùng báo chờ mô hình, vẫn gõ máy', () => {
  const c = fakeController();
  const d = new LiveDirector(c, () => {});
  d.start('x');
  d.handle({ stage: 'task_started', task_id: 'T1', domain: 'hr' });
  d.handle({ stage: 'task_started', task_id: 'T2', domain: 'finance' });
  d.waiting(4);
  for (const who of ['hr', 'finance']) {
    const last = acts(c, who).at(-1);
    assert.equal(last[2], 'working_computer'); assert.match(last[3], /chờ mô hình · 4 giây/);
  }
});

test('xong việc: chuyên gia bỏ hồ sơ, gửi kết quả bay tới Integrator; hết lượt thì về ngủ', () => {
  const c = fakeController();
  const d = new LiveDirector(c, () => {});
  d.start('x');
  d.handle({ stage: 'task_started', task_id: 'T1', domain: 'hr' });
  d.handle({ stage: 'task_completed', result: { task_id: 'T1', domain: 'hr', status: 'COMPLETE' } });
  const last = acts(c, 'hr').at(-1);
  assert.equal(last[2], 'completed'); assert.equal(last[4], 'none');
  assert.deepEqual(scenes(c).at(-1).dispatch, { from: 'hr', toList: ['integrator'] });
  d.handle({ stage: 'synthesis_started' });
  d.handle({ stage: 'run_finished' });
  assert.ok(c.calls.some(x => x[0] === 'sleep' && x[1].includes('hr')));
});

// Thời gian thật / Dễ theo dõi (23/11): Dễ theo dõi thì robot tự đi tới đưa hồ sơ, đang đi thì lệnh mới chờ trao xong.
function walkController() {
  const c = fakeController();
  c.walks = [];
  c.walkAndHandoff = (from, to, item, label, onArrive) => { c.calls.push(['walk', from, to, item]); c.walks.push({ from, to, onArrive }); };
  return c;
}

test('Dễ theo dõi: Orchestrator tự đi giao việc lần lượt cho từng chuyên gia; Thời gian thật thì gói bay', () => {
  const c = walkController();
  const d = new LiveDirector(c, () => {});
  d.setTempo('easy');
  d.start('x');
  d.handle({ stage: 'task_started', task_id: 'T1', domain: 'hr' });
  d.handle({ stage: 'task_started', task_id: 'T2', domain: 'finance' });
  assert.deepEqual(c.walks.map(w => [w.from, w.to]), [['orchestrator', 'hr']], 'việc thứ hai chờ Orchestrator trao xong việc đầu');
  c.walks[0].onArrive();
  assert.deepEqual(c.walks.map(w => [w.from, w.to]), [['orchestrator', 'hr'], ['orchestrator', 'finance']]);
  assert.ok(!scenes(c).some(s => s.dispatch), 'không ném gói khi đã tự đi');
  const r = walkController();
  const d2 = new LiveDirector(r, () => {});
  d2.start('x');  // mặc định Thời gian thật
  d2.handle({ stage: 'task_started', task_id: 'T1', domain: 'hr' });
  assert.equal(r.walks.length, 0);
  assert.deepEqual(scenes(r).at(-1).dispatch, { from: 'orchestrator', toList: ['hr'] });
});

test('Dễ theo dõi: chuyên gia mang kết quả tới Integrator; hết lượt khi đang đi thì trao xong mới ngủ', () => {
  const c = walkController();
  const d = new LiveDirector(c, () => {});
  d.setTempo('easy');
  d.start('x');
  d.handle({ stage: 'task_started', task_id: 'T1', domain: 'hr' });
  c.walks[0].onArrive();
  d.handle({ stage: 'task_completed', result: { task_id: 'T1', domain: 'hr', status: 'COMPLETE' } });
  assert.deepEqual(c.walks.at(-1).from, 'hr'); assert.deepEqual(c.walks.at(-1).to, 'integrator');
  d.handle({ stage: 'synthesis_started' });
  d.handle({ stage: 'run_finished' });
  assert.ok(!c.calls.some(x => x[0] === 'sleep' && x[1].includes('hr')), 'đang đi thì chưa ngủ');
  c.walks.at(-1).onArrive();
  assert.ok(c.calls.some(x => x[0] === 'sleep' && x[1].includes('hr')), 'trao xong thì về ngủ');
});

test('câu đơn giản có T1 (máy chủ mới): chuyên gia ngành là người viết, Integrator chỉ nhận kết quả', () => {
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('Đi muộn 4 lần bị gì?');
  d.handle({ type: 'progress', stage: 'product_request_routing', classification: 'SIMPLE_PROJECT_QUESTION' });
  d.handle({ type: 'progress', stage: 'task_started', task_id: 'T1', domain: 'hr' });
  d.handle({ type: 'progress', stage: 'vanilla_retrieval', selected_count: 1 });
  d.handle({ type: 'answer', text: 'Khiển trách' });
  assert.match(acts(c, 'hr').at(-1)[3], /đang viết câu trả lời/);
  assert.ok(!c.calls.some(x => x[0] === 'act' && x[1] === 'integrator' && /đang viết/.test(x[3])));
  d.handle({ type: 'progress', stage: 'task_completed', result: { task_id: 'T1', domain: 'hr', status: 'COMPLETE' } });
  d.handle({ type: 'progress', stage: 'run_finished' });
  assert.ok(st.steps.some(s => s.key === 'task-T1' && s.actor === 'hr' && s.state === 'done'));
});

test('agent_tool search: Dễ theo dõi thì chuyên gia tự tới tủ; Thời gian thật thì RAG gửi gói; added=0 không gửi gì', () => {
  const easy = fakeController();
  const d = new LiveDirector(easy, () => {});
  d.setTempo('easy');
  d.start('x');
  d.handle({ stage: 'task_started', task_id: 'T1', domain: 'finance' });
  d.handle({ stage: 'agent_tool', task_id: 'T1', domain: 'finance', tool: 'search', added: 3 });
  const f = acts(easy, 'finance').at(-1);
  assert.equal(f[2], 'cabinet_rag'); assert.equal(f[5], 'cabinet'); assert.match(f[3], /3 đoạn mới/);
  d.handle({ stage: 'agent_tool_result', task_id: 'T1', domain: 'finance', tool: 'search', before: 'NO_EVIDENCE', after: 'COMPLETE' });
  const back = acts(easy, 'finance').at(-1);
  assert.equal(back[5], undefined, 'về bàn'); assert.match(back[3], /trả lời được sau khi tìm thêm/);

  const rt = fakeController();
  const r = new LiveDirector(rt, () => {});
  r.start('x');
  r.handle({ stage: 'task_started', task_id: 'T1', domain: 'finance' });
  r.handle({ stage: 'agent_tool', task_id: 'T1', domain: 'finance', tool: 'search', added: 2 });
  assert.deepEqual(scenes(rt).at(-1).dispatch, { from: 'rag', toList: ['finance'] });
  const before = scenes(rt).length;
  r.handle({ stage: 'agent_tool', task_id: 'T1', domain: 'finance', tool: 'search', added: 0 });
  assert.ok(!scenes(rt).slice(before).some(s => s.dispatch), 'không có đoạn mới thì không gửi gói');
  assert.match(acts(rt, 'rag').at(-1)[3], /Không có đoạn mới/);
});

test('review_revision + synthesis_started(revision): Reviewer trả bài, Integrator viết lại trong bước "Viết lại theo góp ý"', () => {
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('x');
  d.handle({ stage: 'synthesis_started', task_count: 2 });
  d.handle({ stage: 'review_started' });
  d.handle({ stage: 'review_finished', review_status: 'ok', checked: 4, unsupported: 2 });
  d.handle({ stage: 'review_revision', unsupported: 2 });
  assert.ok(scenes(c).some(s => s.dispatch?.from === 'reviewer' && s.dispatch.toList[0] === 'integrator'));
  assert.match(acts(c, 'reviewer').at(-1)[3], /2 ý chưa có căn cứ/);
  d.handle({ stage: 'synthesis_started', task_count: 2, revision: true });
  d.handle({ stage: 'run_finished' });
  assert.deepEqual(st.steps.filter(s => s.actor === 'integrator').map(s => s.key), ['write', 'revise']);
});

test('câu đơn giản: Reviewer trả bài cho chuyên gia của T1 (không phải Integrator)', () => {
  const c = fakeController();
  const d = new LiveDirector(c, () => {});
  d.start('x');
  d.handle({ stage: 'task_started', task_id: 'T1', domain: 'hr' });
  d.handle({ stage: 'review_revision', task_id: 'T1', unsupported: 1 });
  assert.ok(scenes(c).some(s => s.dispatch?.from === 'reviewer' && s.dispatch.toList[0] === 'hr'));
});

test('Thời gian thật: bộ nhịp áp sự kiện ngay (không giữ 0,7 giây)', () => {
  const clock = fakeClock();
  const c = fakeController();
  let st;
  const d = new LiveDirector(c, s => { st = s; });
  d.start('x');
  const pacer = new LivePacer(d, { clock, minStepMs: 0 });
  pacer.push({ stage: 'planning_generation' });
  pacer.push({ stage: 'plan_verification' });
  clock.advance(0);
  assert.equal(st.headline, 'Reviewer kiểm tra kế hoạch');
  pacer.dispose();
});
