import { Children, cloneElement, isValidElement, useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import gsap from 'gsap';
import { useGSAP } from '@gsap/react';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { ScrollSmoother } from 'gsap/ScrollSmoother';
import { SplitText } from 'gsap/SplitText';
import { ArrowRight, ArrowUp, ArrowUpRight, Menu, X, Play, Volume2, VolumeX, Database, Code2, Shield, FileText, Check, Upload, Search, ListTree, Filter, Users, Layers, Cpu, FileCheck2, Bot, CreditCard, Building2, RefreshCw, KeyRound, Route, Laptop, ScrollText, MessageSquareText } from 'lucide-react';
import { BrandLogo } from '../components/BrandLogo';
import { AssistantRobot } from '../components/robot/AssistantRobot';
import type { RobotState } from '../components/robot/robotEngine';
import '@fontsource/be-vietnam-pro/800.css';
import '@fontsource/be-vietnam-pro/900.css';
import '@fontsource-variable/inter-tight';
import '../styles/landing-2026.css';
import '../styles/landing-paper.css';
import { PaperStage, StorySky, storyFx, PAPER_CHAPTERS, PAPERS } from '../components/landing/PaperStory';
import { sfx, setSound, soundPref } from '../components/landing/sound';
import { armIntro } from '../components/StudioIntro';
gsap.registerPlugin(useGSAP, ScrollTrigger, ScrollSmoother, SplitText);
// Thanh địa chỉ trên điện thoại co giãn không làm ScrollTrigger đo lại toàn trang (gây giật).
ScrollTrigger.config({ ignoreMobileResize: true, limitCallbacks: true });
// Kéo thanh cuộn vụt qua một phần: hiệu ứng xuất hiện của phần đó hoàn tất ngay thay vì dồn chạy cùng lúc (người xem đã lướt qua).
ScrollTrigger.defaults({ fastScrollEnd: true });

// Nội dung bám theo chức năng đã có trong mã; không có số đo kết quả vì thực nghiệm chưa xong.
const NAV = [['#cau-chuyen', 'Câu chuyện'], ['#chuyen-gia', 'Tác tử'], ['#kich-ban', 'Kịch bản'], ['#phuong-phap', 'Phương pháp'], ['#nghien-cuu', 'Nghiên cứu']];
const AGENTS = [
  { Icon: Database, label: 'Dữ liệu', name: 'Database Analyst', task: 'Lược đồ giao dịch', tone: 'db', role: 'Mô hình dữ liệu, chỉ mục, giao dịch và lưu trữ.', reads: ['Lược đồ bảng', 'Khóa và ràng buộc', 'Quy tắc giao dịch'], gives: 'Thiết kế bảng, khóa chống lặp và ranh giới giao dịch.', files: ['luoc-do-giao-dich.sql', 'bang-payments.sql', 'khoa-idempotency.sql'] },
  { Icon: Code2, label: 'API / kiến trúc', name: 'API/Architecture Analyst', task: 'Hợp đồng API', tone: 'api', role: 'Hợp đồng API, định tuyến và luồng giao tiếp.', reads: ['Đặc tả endpoint', 'Request / response', 'Luồng gọi lại'], gives: 'Hợp đồng endpoint và cách phản hồi khi yêu cầu bị gửi lặp.', files: ['dac-ta-thanh-toan.md', 'webhook-api.md', 'rang-buoc-chung.md'] },
  { Icon: Shield, label: 'Bảo mật', name: 'Security Analyst', task: 'Phân quyền', tone: 'sec', role: 'Xác thực, phân quyền và bảo vệ dữ liệu.', reads: ['Chính sách xác thực', 'Phân quyền', 'Chữ ký webhook'], gives: 'Quy tắc truy cập và cách kiểm tra nguồn gửi.', files: ['chinh-sach-bao-mat.md', 'phan-quyen-rbac.md', 'chu-ky-hmac.md'] },
];
const STEPS = [
  { Icon: Search, art: 0, title: 'Hiểu yêu cầu', body: 'Đọc câu hỏi, rút ra những nghĩa vụ bắt buộc phải đáp ứng và các mối quan tâm.' },
  { Icon: Database, art: 4, title: 'Truy xuất để lập kế hoạch', body: 'Tìm tài liệu định hướng trong kho của bạn trước khi lập kế hoạch.' },
  { Icon: ListTree, art: 1, title: 'Lập kế hoạch', body: 'Mô hình sinh kế hoạch JSON theo cấu trúc chặt và phân rã thành nhiệm vụ.' },
  { Icon: FileCheck2, art: 3, title: 'Kiểm tra kế hoạch', body: 'Kế hoạch được kiểm tra; sai thì sửa một lần, vẫn sai thì từ chối, không đoán bừa.' },
  { Icon: Filter, art: 2, title: 'Chuẩn hóa nhiệm vụ', body: 'Gộp nhiệm vụ trùng, kiểm tra mọi nghĩa vụ đều có nhiệm vụ phủ rồi mới bàn giao.' },
  { Icon: Layers, art: 5, title: 'Truy xuất và chia ngân sách', body: 'Mỗi nhiệm vụ truy xuất riêng; ngân sách token chia theo nhu cầu của từng nhiệm vụ.' },
  { Icon: Cpu, art: 6, title: 'Thực thi nhiệm vụ', body: 'Tác tử bảo mật, cơ sở dữ liệu, API/kiến trúc làm phần việc của mình trên mô hình cục bộ.' },
  { Icon: Users, art: 7, title: 'Tổng hợp', body: 'Ghép kết quả thành một câu trả lời có trích dẫn và lưu lại lượt chạy để đối chiếu.' },
];
const METHODS = [
  { key: 'A', v: 'V', name: 'Vanilla RAG', body: 'Một lượt truy xuất rồi trả lời ngay, không lập kế hoạch. Làm mốc đối chứng.' },
  { key: 'B', v: 'M', name: 'Multi-Agent cơ bản', body: 'Có chia việc cho các tác tử, nhưng không kiểm tra kế hoạch, không chuẩn hóa và không tối ưu ngữ cảnh.' },
  { key: 'C', v: 'A', name: 'Điều phối đầy đủ', body: 'Phương pháp đề xuất: lập kế hoạch có kiểm tra, chuẩn hóa nhiệm vụ, rồi chia ngân sách token theo nhu cầu truy xuất của từng nhiệm vụ.' },
];
const CASES = [
  { Icon: CreditCard, title: 'Cổng thanh toán', q: 'Thiết kế luồng thanh toán không xử lý trùng, có kiểm soát quyền truy cập.', tags: ['Khóa chống lặp', 'Giao dịch', 'Webhook'], tone: 'blue', files: ['dac-ta-thanh-toan.md', 'luoc-do-giao-dich.sql'] },
  { Icon: Building2, title: 'Nền tảng nhiều tổ chức', q: 'Thiết kế dịch vụ dùng chung cho nhiều tổ chức, bảo đảm dữ liệu được cách ly.', tags: ['Cách ly dữ liệu', 'Phạm vi API', 'Phân quyền theo hàng'], tone: 'violet', files: ['mo-hinh-to-chuc.sql', 'pham-vi-api.md'] },
  { Icon: RefreshCw, title: 'Đồng bộ sự kiện', q: 'Đồng bộ trạng thái đơn hàng khi sự kiện có thể đến trễ hoặc bị lặp.', tags: ['Outbox', 'Thử lại', 'Xác thực nguồn'], tone: 'teal', files: ['thiet-ke-outbox.md', 'hop-dong-su-kien.md'] },
  { Icon: KeyRound, title: 'Xác thực webhook', q: 'Xác thực webhook bằng chữ ký HMAC và chống phát lại yêu cầu cũ.', tags: ['HMAC', 'Chống phát lại', 'Khóa bí mật'], tone: 'amber', files: ['chu-ky-hmac.md', 'chinh-sach-khoa.md'] },
  { Icon: Route, title: 'API Gateway', q: 'Đặc tả API Gateway với định tuyến, token và phân quyền theo vai trò.', tags: ['Định tuyến', 'Token', 'RBAC'], tone: 'rose', files: ['dac-ta-gateway.md', 'phan-quyen-rbac.md'] },
];
const STACK = [['Ollama', 'chạy mô hình cục bộ'], ['Qwen3:4b', 'mô hình sinh'], ['nomic-embed-text', 'embedding'], ['Qdrant', 'kho vector'], ['FastAPI', 'điều phối'], ['SQLAlchemy', 'lưu lượt chạy'], ['PostgreSQL', 'cơ sở dữ liệu'], ['React', 'giao diện']];
const FAQS = [
  ['OrchestrIQ Studio dành cho ai?', 'Kỹ sư phần mềm, trưởng nhóm kỹ thuật và người nghiên cứu cần phân tích một yêu cầu liên quan nhiều chuyên môn, và muốn thấy tài liệu nào đứng sau câu trả lời.'],
  ['Dữ liệu của tôi có bị gửi ra ngoài không?', 'Luồng phân tích dùng Ollama, Qdrant và PostgreSQL chạy trên máy của bạn. Việc vận hành thực tế phụ thuộc cấu hình và các dịch vụ bạn đang bật.'],
  ['Ba tác tử có phải ba mô hình khác nhau?', 'Không. Cả ba dùng chung mô hình qwen3:4b, khác nhau ở nhiệm vụ, chỉ dẫn và phần tài liệu được giao.'],
  ['Phương pháp mới đã được chứng minh tốt hơn chưa?', 'Chưa. Nhóm đang chạy thực nghiệm thử. Kết quả chỉ được công bố khi thực nghiệm chính hoàn tất theo quy trình đã khóa trước, kể cả khi kết quả không như kỳ vọng.'],
  ['Tôi cần gì để chạy Studio?', 'Một máy tính có Ollama với mô hình qwen3:4b và nomic-embed-text, PostgreSQL, cùng backend FastAPI và giao diện React của dự án. Hướng dẫn cài đặt và vận hành đi kèm sản phẩm.'],
];
const MARQUEE = ['Phân rã', 'Truy xuất', 'Phân bổ', 'Kiểm chứng', 'Tổng hợp'];

type Variant = 'overload' | 'split' | 'alloc' | 'final' | 'V' | 'M' | 'F' | 'A';
// Mỗi biến thể là một trạng thái minh họa, không phải số đo: vòng tròn chỉ mức đầy ngữ cảnh tương đối.
const FLOW: Record<Variant, { fill: number[]; docs: number; brief: boolean; tasks: boolean; final: boolean; alert?: string; tone: 'bad' | 'ok' | 'done' }> = {
  overload: { fill: [1, 1, 1], docs: 8, brief: false, tasks: false, final: false, alert: 'Ngữ cảnh quá tải', tone: 'bad' },
  split: { fill: [0.08, 0.08, 0.08], docs: 0, brief: false, tasks: true, final: false, tone: 'ok' },
  alloc: { fill: [0.62, 0.4, 0.82], docs: 3, brief: false, tasks: true, final: false, tone: 'ok' },
  final: { fill: [1, 1, 1], docs: 3, brief: false, tasks: true, final: true, tone: 'done' },
  V: { fill: [1], docs: 9, brief: false, tasks: false, final: false, alert: 'Một ngữ cảnh cho mọi chuyên môn', tone: 'bad' },
  M: { fill: [1, 1, 1], docs: 8, brief: false, tasks: true, final: false, alert: 'Cùng tài liệu bị gửi lặp ba lần', tone: 'bad' },
  F: { fill: [0.6, 0.6, 0.6], docs: 3, brief: false, tasks: true, final: false, tone: 'ok' },
  A: { fill: [0.62, 0.4, 0.82], docs: 3, brief: false, tasks: true, final: false, tone: 'ok' },
};
const X3 = [108, 300, 492];

function Paper({ req, i }: { req?: boolean; i: number }) {
  return <i className={`lp-paper${req ? ' is-req' : ''}`} style={{ '--j': i, '--r': `${(i % 2 ? 1 : -1) * (2 + (i % 3))}deg` } as React.CSSProperties}/>;
}

// Ẩn dụ bàn làm việc: giấy tờ = tài liệu, khay = ngữ cảnh của tác tử. Chỉ minh họa, không phải số đo.
function Flow({ v }: { v: Variant }) {
  const f = FLOW[v];
  const single = v === 'V';
  const nodes = single ? [{ Icon: Bot, label: 'Một mô hình', task: 'Mọi nhiệm vụ', tone: 'one' }] : AGENTS;
  const xs = single ? [300] : X3;
  const over = f.tone === 'bad';
  return <div className={`lp-flow is-${f.tone}`} data-v={v} aria-hidden="true">
    <svg className="lp-flow-lines" viewBox="0 0 600 440" preserveAspectRatio="none">
      <defs><marker id={`lp-arrow-${v}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker></defs>
      {xs.map(x => <path key={`i${x}`} markerEnd={`url(#lp-arrow-${v})`} d={`M300 70 C300 118, ${x} 112, ${x} 162`}/>)}
      {f.final && xs.map(x => <path key={`o${x}`} className="is-out" markerEnd={`url(#lp-arrow-${v})`} d={`M${x} 346 C${x} 368, 300 362, 300 378`}/>)}
    </svg>
    <span className="lp-flow-q"><b>Bạn</b>Thiết kế luồng thanh toán an toàn?</span>
    {f.brief && <span className="lp-sticky"><i className="lp-tape"/><strong>Ghi chú chung</strong>Shared Brief · gom một lần</span>}
    {f.alert && <span className="lp-stamp">{f.alert}</span>}
    {nodes.map(({ Icon, label, task, tone }, i) => <div key={tone} className={`lp-desk is-${tone}`} style={{ left: `${xs[i] / 6}%`, '--d': `${i * 0.09}s` } as React.CSSProperties}>
      <div className="lp-desk-head"><span className="lp-sa-icon"><Icon size={16}/></span><strong>{label}</strong></div>
      {f.tasks && <em className="lp-desk-task">{task}</em>}
      <div className="lp-tray">
        {Array.from({ length: f.docs }, (_, j) => <Paper key={j} i={j} req={f.brief && j === 0}/>)}
        {over && [0, 1, 2].map(j => <i key={`f${j}`} className="lp-paper is-fall" style={{ '--j': j } as React.CSSProperties}/>)}
      </div>
      <div className="lp-cap-bar"><span>Ngữ cảnh</span><b><i style={{ width: `${f.fill[i] * 100}%` }}/></b></div>
    </div>)}
    {f.final && <div className="lp-final-doc"><FileText size={16}/><div><strong>Bản thiết kế tổng hợp</strong><span>Dữ liệu · API · Bảo mật</span></div><em>Đã đối chiếu</em></div>}
  </div>;
}

// Minh họa từng bước của một lượt chạy, vẽ như mảnh giao diện thật. Nội dung là ví dụ theo kịch bản
// thanh toán; độ dài các thanh chỉ minh họa, không phải số đo.
const RUN_LANES = [
  { tone: 'db', label: 'Dữ liệu', task: 'Bảng giao dịch, khóa chống lặp', docs: ['luoc-do-giao-dich.sql', 'khoa-idempotency.sql'], w: 62, out: 'Lưu khóa chống lặp trong bảng giao dịch.' },
  { tone: 'api', label: 'API / kiến trúc', task: 'Endpoint thanh toán, webhook', docs: ['dac-ta-thanh-toan.md'], w: 40, out: 'Trả lại kết quả cũ khi yêu cầu bị gửi lặp.' },
  { tone: 'sec', label: 'Bảo mật', task: 'Phân quyền, chữ ký webhook', docs: ['chinh-sach-bao-mat.md', 'chu-ky-hmac.md'], w: 82, out: 'Kiểm tra chữ ký HMAC trước khi nhận webhook.' },
] as const;
const ii = (i: number) => ({ '--i': i } as React.CSSProperties);

// Thanh tiêu đề của từng khung minh họa: tên bước như Studio ghi lại, và trạng thái.
const RUN_HEAD = [['yêu cầu · rút nghĩa vụ', '3 nghĩa vụ'], ['truy xuất · kho tri thức cục bộ', 'Qdrant'], ['planner · qwen3:4b', 'JSON'], ['validate_tasks()', 'Đạt'],
  ['chuẩn hóa · gộp trùng', 'Phủ đủ'], ['truy xuất theo nhiệm vụ', '3 tác tử'], ['thực thi · Ollama cục bộ', 'Đang chạy'], ['tổng hợp · có trích dẫn', 'Đã lưu']];

function RunArt({ k }: { k: number }) {
  return <div className="ra-frame"><div className="ra-head"><span>{RUN_HEAD[k][0]}</span><em>{RUN_HEAD[k][1]}</em></div><RunArtBody k={k}/></div>;
}

function RunArtBody({ k }: { k: number }) {
  if (k === 0) return <div className="ra">
    <span className="ra-cap">Câu hỏi của bạn</span>
    <p className="ra-q">Thiết kế luồng <u className="is-r3">thanh toán</u> <u className="is-r1">không xử lý trùng</u>, có <u className="is-r2">kiểm soát quyền truy cập</u>.</p>
    <div className="ra-tags">{[['r1', 'Không xử lý hai lần'], ['r2', 'Chỉ người có quyền'], ['r3', 'Đủ luồng thanh toán']].map(([r, t], i) => <span key={r} className={`is-${r}`} style={ii(i)}><b>{r}</b>{t}</span>)}</div>
  </div>;
  if (k === 1) return <div className="ra">
    <div className="ra-search"><Search size={17}/>chiến lược thanh toán an toàn</div>
    {[['luoc-do-giao-dich.sql', 'Dữ liệu', 'db', 88], ['dac-ta-thanh-toan.md', 'API', 'api', 72], ['chinh-sach-bao-mat.md', 'Bảo mật', 'sec', 58]].map(([f, t, tone, w], i) => <div key={f as string} className="ra-hit" style={ii(i)}>
      <FileText size={16}/><span>{f}</span><em className={`is-${tone}`}>{t}</em><b><i style={{ width: `${w}%` }}/></b>
    </div>)}
  </div>;
  if (k === 2) return <div className="ra">
    <span className="ra-cap">Kế hoạch JSON do mô hình sinh</span>
    <pre className="ra-code">{[
      <>{'{ '}<b>"id"</b>: <em>"t1"</em>, <b>"domain"</b>: <em>"database"</em>{' }'}</>,
      <>{'{ '}<b>"id"</b>: <em>"t2"</em>, <b>"domain"</b>: <em>"api"</em>, <b>"depends_on"</b>: [<em>"t1"</em>]{' }'}</>,
      <>{'{ '}<b>"id"</b>: <em>"t3"</em>, <b>"domain"</b>: <em>"security"</em>{' }'}</>,
      <><b>"covers"</b>: [<em>"r1"</em>, <em>"r2"</em>, <em>"r3"</em>]</>,
    ].map((l, i) => <span key={i} style={ii(i)}>{l}</span>)}</pre>
  </div>;
  if (k === 3) return <div className="ra ra-split">
    <ul className="ra-checks">{['Đúng cấu trúc JSON', 'Mỗi nhiệm vụ một chuyên môn', 'Không phụ thuộc vòng', 'Phủ đủ r1, r2, r3'].map((t, i) => <li key={t} style={ii(i)}><Check size={14}/>{t}</li>)}</ul>
    <div className="ra-verdict"><span className="ra-stamp">Hợp lệ</span><small>Sai thì sửa một lần, vẫn sai thì từ chối.</small></div>
  </div>;
  if (k === 4) return <div className="ra">
    <div className="ra-dup"><span>Thiết kế bảng giao dịch</span><span className="is-dup">Thiết kế bảng giao dịch</span></div>
    <div className="ra-cover">{['r1', 'r2', 'r3'].map((r, i) => <span key={r} style={ii(i)}><b>{r}</b>đã được phủ<Check size={14}/></span>)}</div>
  </div>;
  if (k === 5) return <div className="ra">
    {RUN_LANES.map(({ tone, label, docs, w }, i) => <div key={tone} className={`ra-lane is-${tone}`} style={ii(i)}>
      <strong>{label}</strong><span className="ra-chips">{docs.map(d => <em key={d}>{d}</em>)}</span><b><i style={{ width: `${w}%` }}/></b>
    </div>)}
    <span className="ra-cap">Ngân sách token chia theo nhu cầu từng nhiệm vụ</span>
  </div>;
  if (k === 6) return <div className="ra">
    {RUN_LANES.map(({ tone, label, task }, i) => <div key={tone} className={`ra-lane ra-exec is-${tone}`} style={ii(i)}>
      <strong>{label}</strong><span className="ra-task">{task}</span><span className="ra-done">Xong</span><b><i/></b>
    </div>)}
  </div>;
  return <div className="ra ra-doc">
    <div className="ra-doc-head"><FileText size={18}/><strong>Bản thiết kế tổng hợp</strong><span className="ra-stamp">Đã đối chiếu</span></div>
    {RUN_LANES.map(({ tone, out, docs }, i) => <p key={tone} className={`is-${tone}`} style={ii(i)}>{out}<em>{docs[0]}</em></p>)}
  </div>;
}

// Tiêu đề phần kêu gọi cuối trang, tách từng ký tự để làm sóng chữ khi rê chuột.
// Dòng 2 tô chuyển sắc theo vị trí ký tự (thay cho background-clip, vốn hỏng khi từng ký tự có transform).
const CTA_LINES = ['Thử với bài toán', 'của chính bạn.'];
const ctaMix = (t: number) => `rgb(${Math.round(127 - 84 * t)},${Math.round(211 - 86 * t)},${Math.round(255 - 22 * t)})`;
function CtaTitle({ onRipple }: { onRipple: (e: React.MouseEvent<HTMLElement>) => void }) {
  return <h2 className="lp-cta-title" aria-label={CTA_LINES.join(' ')} onClick={onRipple}>{CTA_LINES.map((line, li) => {
    const words = line.normalize('NFC').split(' '), n = words.join('').length;
    let k = 0;
    return <span key={line} className={`lp-cta-line${li ? ' is-accent' : ''}`} aria-hidden="true">{words.map((w, wi) => <span key={wi}>{wi > 0 && ' '}<span className="lp-cw">{[...w].map(c => {
      const t = k++ / Math.max(n - 1, 1);
      return <span key={k} className="lp-ch" style={li ? { color: ctaMix(t) } : undefined}><i>{c}</i></span>;
    })}</span></span>)}</span>;
  })}</h2>;
}

// Phần giới thiệu: một lượt chạy thu nhỏ. Tin nhắn câu hỏi → Robot C27 nhận và chia việc → ba thẻ tác tử bay ra,
// đọc tài liệu → từng phần được đưa vào bản trả lời có nguồn. Nội dung là ví dụ theo kịch bản thanh toán.
const SCENE_ROBOT: RobotState[] = ['idle', 'receiving', 'assigning', 'executing', 'synthesizing', 'completed'];
const SCENE_STATUS = ['Đang chờ câu hỏi', 'Đã nhận câu hỏi', 'Đang chia việc', 'Ba tác tử đang đọc tài liệu', 'Đang tổng hợp', 'Hoàn tất, có nguồn'];
// Lời lẽ đời thường để người không chuyên cũng hiểu; mỗi tác tử một việc, một tài liệu, một ý trong câu trả lời.
const SCENE_AGENTS = [
  { tone: 'db', task: 'Ghi nhận giao dịch', doc: 'Thiết kế dữ liệu', point: 'Mỗi lần thanh toán có một mã riêng, chỉ được ghi nhận một lần.' },
  { tone: 'api', task: 'Cách hệ thống phản hồi', doc: 'Đặc tả thanh toán', point: 'Khách bấm lại thì trả về kết quả cũ, không trừ tiền thêm.' },
  { tone: 'sec', task: 'Xác minh nguồn thông báo', doc: 'Chính sách bảo mật', point: 'Chỉ tin thông báo có chữ ký thật của cổng thanh toán.' },
] as const;
function RunScene({ store, live }: { store: ScrollValue; live: boolean }) {
  const v = useValue(store);
  const k = live ? v : 5; // không có hiệu ứng cuộn: hiện sẵn trạng thái hoàn tất
  return <div className="lp-sc" data-live={live ? '' : undefined}>
    <div className="lp-sc-pos is-msg"><div className="lp-card lp-sc-msg"><span className="lp-sc-who">Bạn</span><p>Làm sao để khách không bị trừ tiền hai lần khi bấm thanh toán?</p></div></div>
    <div className="lp-sc-pos is-bot" aria-hidden="true"><div className="lp-sc-bot">
      <AssistantRobot size={180} interactive={false} state={SCENE_ROBOT[k]} colorConfig={{ shell: '#14263a', trim: '#c9d7ee', screen: '#7fd3ff' }}/>
      <span className="lp-sc-status" key={k}>{SCENE_STATUS[k]}</span>
    </div></div>
    {AGENTS.map(({ Icon, label, tone }, i) => <div key={tone} className={`lp-sc-pos is-agent is-a${i}`}>
      <div className={`lp-card lp-agent-card lp-sc-agent is-${tone}`}>
        <span className="lp-sa-icon"><Icon size={20}/></span>
        <div><strong>{label}</strong><span>{SCENE_AGENTS[i].task}</span><small><FileText size={12}/>Đang đọc: {SCENE_AGENTS[i].doc}</small><b className="lp-sc-read"><i/></b></div>
      </div>
    </div>)}
    {/* Bản trả lời kiểu tin nhắn: tóm tắt, ba ý đánh số có chú thích nguồn, danh sách nguồn ở cuối */}
    <div className="lp-sc-pos is-ans"><div className="lp-card lp-sc-ans">
      <div className="lp-sc-ans-head"><span className="lp-sc-ava"><Bot size={15}/></span><strong>OrchestrIQ</strong><em><Check size={12}/>Đã đối chiếu</em></div>
      <p className="lp-sc-sum">Có 3 việc cần làm:</p>
      <ol className="lp-sc-points">{SCENE_AGENTS.map((a, i) => <li key={a.tone} className={`lp-sc-line is-${a.tone}`}><b>{i + 1}</b><span>{a.point}</span></li>)}</ol>
      <div className="lp-sc-done"><span className="lp-sc-src-k">Nguồn đã dùng</span>
        <ul>{SCENE_AGENTS.map((a, i) => <li key={a.tone} className={`is-${a.tone}`}><b>{i + 1}</b><FileText size={13}/>{a.doc}</li>)}</ul></div>
    </div></div>
  </div>;
}

function VideoDialog({ onClose }: { onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const smoother = ScrollSmoother.get();
    smoother?.paused(true);
    document.body.style.overflow = 'hidden';
    box.current?.querySelector<HTMLElement>('button')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab' || !box.current) return;
      const items = [...box.current.querySelectorAll<HTMLElement>('button, video')];
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = ''; smoother?.paused(false); opener?.focus(); };
  }, [onClose]);
  return <div className="lp-video-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="lp-video-box" ref={box} role="dialog" aria-modal="true" aria-labelledby="lp-video-title">
      <div className="lp-video-bar"><strong id="lp-video-title">OrchestrIQ Studio trong 1 phút</strong><button type="button" onClick={onClose} aria-label="Đóng video"><X size={20}/></button></div>
      <video src="/media/orchestriq-intro.mp4" poster="/media/orchestriq-intro-poster.jpg" controls autoPlay playsInline preload="metadata" tabIndex={0}/>
    </div>
  </div>;
}

function VideoTeaser({ onOpen, children }: { onOpen: () => void; children?: ReactNode }) {
  return <button type="button" className="lp-teaser" onClick={onOpen} aria-label="Xem video giới thiệu OrchestrIQ Studio, khoảng 1 phút">
    <img src="/media/orchestriq-intro-poster.jpg" alt="" width={1280} height={720} loading="lazy"/>
    <span className="lp-teaser-play"><Play size={26} fill="currentColor"/></span>
    <span className="lp-teaser-label">{children}</span>
  </button>;
}


// Giá trị đổi theo cuộn (chương câu chuyện, bước đường ray): chỉ khối nhỏ đọc nó render lại,
// không render lại cả trang mỗi lần qua mốc (rất tốn ở React 19 chế độ phát triển, gây giật khi cuộn).
type ScrollValue = { v: number; subs: Set<() => void> };
const createValue = (v: number): ScrollValue => ({ v, subs: new Set() });
const setValue = (s: ScrollValue, v: number) => { if (s.v === v) return; s.v = v; s.subs.forEach(f => f()); };
function useValue(s: ScrollValue) {
  return useSyncExternalStore(cb => { s.subs.add(cb); return () => { s.subs.delete(cb); }; }, () => s.v);
}

// Tách tiêu đề chương thành từng từ (giữ thẻ <i>) để mỗi từ lật lên lần lượt khi chương mở.
function riseWords(node: ReactNode): ReactNode {
  let w = 0;
  const split = (n: ReactNode): ReactNode => {
    if (typeof n === 'string') return n.split(/(\s+)/).map((t, k) => !t || /^\s+$/.test(t) ? t
      : <span key={k} className="v4-rw"><span style={{ '--w': w++ } as React.CSSProperties}>{t}</span></span>);
    if (isValidElement<{ children?: ReactNode }>(n)) return cloneElement(n, undefined, Children.map(n.props.children, split));
    return n;
  };
  return split(node);
}

// Tách chữ tiêu đề chương một lần; đổi chương chỉ đổi class, React bỏ qua phần chữ không đổi.
const CHAPTER_TITLES = PAPER_CHAPTERS.map(c => <h2>{riseWords(c.title)}</h2>);
function ChapterCopy({ store }: { store: ScrollValue }) {
  const pch = useValue(store);
  return <>{PAPER_CHAPTERS.map((c, i) => <div key={c.tag} className={`v4-chapter${i === pch ? ' is-on' : ''}${i >= 2 ? ' is-dark' : ''}`} aria-hidden={i !== pch}>
    <p className="v4-kicker">0{i + 1} — {c.tag}</p>{CHAPTER_TITLES[i]}<p>{c.body}</p>
  </div>)}</>;
}

function ChapterTabs({ store }: { store: ScrollValue }) {
  const pch = useValue(store);
  return <div className="v4-tabs" aria-hidden="true">{PAPER_CHAPTERS.map((c, i) => <span key={c.tag} className={i === pch ? 'is-on' : ''}><b/>0{i + 1} {c.tag}</span>)}</div>;
}

function RailCount({ store }: { store: ScrollValue }) {
  const rail = useValue(store);
  return <div className="lp-rail-count" aria-hidden="true"><b key={rail}>{String(rail + 1).padStart(2, '0')}</b><span>/ 08</span><em>{STEPS[rail].title}</em></div>;
}

// Hộp ba điều kiện tự chuyển mỗi 4,5 giây: giữ trạng thái riêng để không render lại cả trang.
function MethodsBox({ motionOn }: { motionOn: boolean }) {
  const [method, setMethod] = useState(2);
  const [autoMethod, setAutoMethod] = useState(true);
  useEffect(() => {
    if (!motionOn || !autoMethod) return;
    const t = window.setInterval(() => setMethod(m => (m + 1) % METHODS.length), 4500);
    return () => window.clearInterval(t);
  }, [motionOn, autoMethod]);
  return <div className="lp-methods-box lp-reveal">
          <div className="lp-methods-tabs" role="tablist" aria-label="Chọn phương pháp">
            {METHODS.map((m, i) => <button key={m.key} role="tab" id={`lp-m-${i}`} aria-selected={method === i} aria-controls="lp-m-panel" tabIndex={method === i ? 0 : -1}
              onClick={() => { setMethod(i); setAutoMethod(false); sfx.tick(); }}
              onKeyDown={e => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); const n = (i + (e.key === 'ArrowRight' ? 1 : METHODS.length - 1)) % METHODS.length; setMethod(n); setAutoMethod(false); document.getElementById(`lp-m-${n}`)?.focus(); } }}>
              <b>{m.key}</b><span>{m.name}</span>
              {method === i && autoMethod && motionOn && <i className="lp-tab-timer" key={method}/>}
            </button>)}
          </div>
          <div className="lp-methods-panel" role="tabpanel" id="lp-m-panel" aria-labelledby={`lp-m-${method}`}>
            <div className="lp-methods-text" key={method}>
              <h3>{METHODS[method].name}{METHODS[method].key === 'C' && <em>Đề xuất</em>}</h3>
              <p>{METHODS[method].body}</p>
            </div>
            <Flow v={METHODS[method].v as Variant} key={`m${method}`}/>
          </div>
  </div>;
}

export function LandingPage() {
  const root = useRef<HTMLDivElement>(null);
  const [fullMotion, setFullMotion] = useState(() => {
    if (new URLSearchParams(window.location.search).get('motion') === 'full') return true;
    // Bật sẵn khi bàn giao hoặc mở trên trình duyệt mới. Không kế thừa
    // giá trị auto do bản cũ tự ghi khi người dùng chưa chọn gì.
    try { return localStorage.getItem('orchestriq-motion-v2') !== 'auto'; } catch { return true; }
  });
  const [systemReduced, setSystemReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [wide, setWide] = useState(() => window.matchMedia('(min-width: 1024px) and (min-height: 600px)').matches);
  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
    const size = window.matchMedia('(min-width: 1024px) and (min-height: 600px)');
    const update = () => { setSystemReduced(reduce.matches); setWide(size.matches); };
    reduce.addEventListener('change', update); size.addEventListener('change', update);
    return () => { reduce.removeEventListener('change', update); size.removeEventListener('change', update); };
  }, []);
  useEffect(() => {
    try { localStorage.setItem('orchestriq-motion-v2', fullMotion ? 'full' : 'auto'); } catch { /* Trình duyệt có thể chặn lưu tùy chọn. */ }
    const url = new URL(window.location.href);
    if (url.searchParams.has('motion')) {
      url.searchParams.delete('motion');
      window.history.replaceState(window.history.state, '', url);
    }
  }, [fullMotion]);
  const motionOn = fullMotion || !systemReduced;
  const pinned = motionOn && wide;
  const [menuOpen, setMenuOpen] = useState(false);
  const [videoOpen, setVideoOpen] = useState(false);
  const closeVideo = useCallback(() => { setVideoOpen(false); sfx.tick(false); }, []);
  const pchStore = useRef(createValue(0)).current;
  const railStore = useRef(createValue(0)).current;
  const sceneStore = useRef(createValue(0)).current;
  const [soundOn, setSoundOn] = useState(soundPref);
  useEffect(() => { setSound(soundOn); }, [soundOn]);
  const toggleSound = () => { const next = !soundOn; setSound(next); setSoundOn(next); if (next) sfx.on(); };
  // Âm theo chương của cảnh chồng tài liệu và theo bước của đường ray; bỏ qua lần render đầu.
  useEffect(() => {
    let from = pchStore.v;
    const onChange = () => {
      const pch = pchStore.v;
      // Thuộc tính data-ch điều khiển nền sáng/tối của cảnh; cập nhật thẳng vào DOM, không render lại trang.
      document.getElementById('cau-chuyen')?.setAttribute('data-ch', String(pch));
      if (from === pch) return;
      if (pch < from) sfx.paper(2);
      else if (pch === 1) sfx.overload();
      else if (pch === 2) { sfx.scan(); window.setTimeout(() => sfx.paper(4), 420); }
      else if (pch === 3) sfx.done();
      from = pch;
    };
    pchStore.subs.add(onChange);
    return () => { pchStore.subs.delete(onChange); };
  }, [pchStore]);
  // Âm khi từng phần xuất hiện, độc lập với chế độ chuyển động; mỗi phần một kiểu âm.
  useEffect(() => {
    const cues: [string, () => void][] = [
      ['.lp-sc', () => sfx.connect()], ['.lp-stack-card', () => sfx.whoosh()], ['.lp-cases-grid', () => sfx.pops(5)],
      ['.lp-methods-box', () => sfx.sparkle(4)], ['.lp-caps-grid', () => sfx.keys(8)], ['.lp-tech', () => sfx.whoosh()],
      ['.lp-mission-rows', () => sfx.sparkle(3)], ['.lp-cta', () => sfx.finale()],
      // Màn hình hẹp không ghim cảnh, nên phát âm khi các khối xuất hiện.
      ...(wide ? [] : [['.v4-paper-flow', () => sfx.paper(4)], ['.lp-night', () => sfx.swell()]] as [string, () => void][]),
    ];
    const triggers = cues.filter(([sel]) => document.querySelector(sel)).map(([sel, play]) => ScrollTrigger.create({ trigger: sel, start: 'top 72%', onEnter: play }));
    return () => triggers.forEach(t => t.kill());
  }, [wide]);
  const lastHover = useRef<Element | null>(null);
  const hoverSound = (e: React.PointerEvent<HTMLElement>) => {
    if (e.pointerType !== 'mouse') return;
    const el = (e.target as HTMLElement).closest('a.lp-btn, .lp-nav a, .lp-link, .lp-login, .lp-sound, .lp-teaser, .lp-methods-tabs button, .lp-faq summary');
    if (el && el !== lastHover.current) sfx.hover();
    lastHover.current = el;
  };
  useEffect(() => {
    const onChange = () => {
      sfx.step(railStore.v);
    };
    railStore.subs.add(onChange);
    return () => { railStore.subs.delete(onChange); };
  }, [railStore]);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [menuOpen]);

  // Tạm dừng mọi animation CSS lặp vô hạn của phần đã cuộn khuất (nét đứt chạy, băng chữ, vầng sáng...): đỡ vẽ lại vô ích.
  useEffect(() => {
    const els = root.current?.querySelectorAll<HTMLElement>('section, .lp-marquee, footer');
    if (!els?.length) return;
    const io = new IntersectionObserver(entries => entries.forEach(e => e.target.classList.toggle('lp-off', !e.isIntersecting)), { rootMargin: '200px 0px' });
    els.forEach(el => io.observe(el));
    return () => io.disconnect();
  }, []);

  // Neo nội bộ: khi ScrollSmoother bật, nhảy bằng smoother để vị trí đúng.
  const jump = (e: React.MouseEvent<HTMLElement>) => {
    const href = (e.target as HTMLElement).closest('a')?.getAttribute('href');
    if (!href?.startsWith('#') || href.length < 2) return;
    sfx.whoosh();
    const target = document.querySelector(href);
    const smoother = ScrollSmoother.get();
    if (!target || !smoother) return;
    e.preventDefault();
    smoother.scrollTo(target, true, 'top 72px');
  };

  // Thẻ trong hero nghiêng nhẹ theo chuột (chỉ chuột, không cảm ứng).
  const parallax = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== 'mouse' || !motionOn) return;
    const r = e.currentTarget.getBoundingClientRect();
    e.currentTarget.style.setProperty('--px', ((e.clientX - r.left) / r.width - 0.5).toFixed(3));
    e.currentTarget.style.setProperty('--py', ((e.clientY - r.top) / r.height - 0.5).toFixed(3));
  };

  // Phần kêu gọi cuối trang: đèn theo con trỏ, sóng chữ nảy quanh con trỏ, biểu tượng lệch theo chiều sâu.
  // Tâm từng ký tự được đo một lần khi chuột vào (tọa độ theo khung phần), tránh đo lại mỗi lần di chuột.
  const ctaChars = useRef<{ el: HTMLElement; x: number; y: number }[]>([]);
  const measureCta = (sec: HTMLElement) => {
    const r = sec.getBoundingClientRect();
    ctaChars.current = [...sec.querySelectorAll<HTMLElement>('.lp-ch')].map(el => { const b = el.getBoundingClientRect(); return { el, x: b.left - r.left + b.width / 2, y: b.top - r.top + b.height / 2 }; });
  };
  const ctaMove = (e: React.PointerEvent<HTMLElement>) => {
    if (e.pointerType !== 'mouse' || !motionOn) return;
    const sec = e.currentTarget, r = sec.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    sec.style.setProperty('--mx', `${x}px`); sec.style.setProperty('--my', `${y}px`);
    sec.style.setProperty('--nx', (x / r.width - 0.5).toFixed(3)); sec.style.setProperty('--ny', (y / r.height - 0.5).toFixed(3));
    if (!ctaChars.current.length) measureCta(sec);
    for (const c of ctaChars.current) c.el.style.setProperty('--lift', Math.max(0, 1 - Math.hypot(x - c.x, (y - c.y) * 1.3) / 170).toFixed(3));
  };
  const ctaLeave = (e: React.PointerEvent<HTMLElement>) => {
    ctaChars.current.forEach(c => c.el.style.setProperty('--lift', '0'));
    ctaChars.current = [];
    e.currentTarget.style.setProperty('--nx', '0'); e.currentTarget.style.setProperty('--ny', '0');
  };
  // Bấm vào tiêu đề: một làn sóng nhảy lan ra từ ký tự gần chỗ bấm.
  const ctaRipple = (e: React.MouseEvent<HTMLElement>) => {
    if (!motionOn) return;
    const chars = [...e.currentTarget.querySelectorAll<HTMLElement>('.lp-ch')];
    let from = 0, best = Infinity;
    chars.forEach((el, i) => { const b = el.getBoundingClientRect(), d = Math.hypot(e.clientX - b.left - b.width / 2, e.clientY - b.top - b.height / 2); if (d < best) { best = d; from = i; } });
    gsap.fromTo(chars, { y: 0 }, { y: -22, duration: 0.22, ease: 'power2.out', yoyo: true, repeat: 1, stagger: { each: 0.025, from } });
    sfx.tick();
  };
  // Nút "hút" nhẹ theo con trỏ.
  const magnet = (e: React.PointerEvent<HTMLElement>) => {
    if (e.pointerType !== 'mouse' || !motionOn) return;
    const r = e.currentTarget.getBoundingClientRect();
    e.currentTarget.style.setProperty('--bx', `${(((e.clientX - r.left) / r.width) - 0.5) * 16}px`);
    e.currentTarget.style.setProperty('--by', `${(((e.clientY - r.top) / r.height) - 0.5) * 12}px`);
  };
  const unmagnet = (e: React.PointerEvent<HTMLElement>) => { e.currentTarget.style.setProperty('--bx', '0px'); e.currentTarget.style.setProperty('--by', '0px'); };

  // Chân trang: đèn theo con trỏ và lớp chữ sáng quanh con trỏ trên tên thương hiệu cỡ lớn.
  const footMove = (e: React.PointerEvent<HTMLElement>) => {
    if (e.pointerType !== 'mouse' || !motionOn) return;
    const f = e.currentTarget, r = f.getBoundingClientRect();
    f.style.setProperty('--fx', `${e.clientX - r.left}px`); f.style.setProperty('--fy', `${e.clientY - r.top}px`);
    const m = f.querySelector<HTMLElement>('.lp-footer-marks');
    if (m) { const b = m.getBoundingClientRect(); m.style.setProperty('--lx', `${e.clientX - b.left}px`); m.style.setProperty('--ly', `${e.clientY - b.top}px`); }
  };

  const tilt = (e: React.PointerEvent<HTMLElement>) => {
    if (e.pointerType !== 'mouse' || !motionOn) return;
    const r = e.currentTarget.getBoundingClientRect();
    e.currentTarget.style.setProperty('--rx', `${((e.clientY - r.top) / r.height - 0.5) * -10}deg`);
    e.currentTarget.style.setProperty('--ry', `${((e.clientX - r.left) / r.width - 0.5) * 12}deg`);
  };
  const untilt = (e: React.PointerEvent<HTMLElement>) => { e.currentTarget.style.setProperty('--rx', '0deg'); e.currentTarget.style.setProperty('--ry', '0deg'); };

  useGSAP(() => {
    const mm = gsap.matchMedia();
    mm.add(fullMotion ? '(min-width: 0px)' : '(prefers-reduced-motion: no-preference)', () => {
      const smoother = wide && window.matchMedia('(pointer: fine)').matches
        ? ScrollSmoother.create({ wrapper: '.lp-smooth', content: '.lp-smooth-content', smooth: 1.1, smoothTouch: false, normalizeScroll: false })
        : null;

      gsap.timeline({ defaults: { ease: 'expo.out' } })
        .from('.lp-hero h1 .lp-line > span', { yPercent: 110, duration: 1.1, stagger: 0.09 })
        .fromTo('.lp-brush path', { strokeDashoffset: 620 }, { strokeDashoffset: 0, duration: 1, ease: 'power2.inOut' }, '-=0.5')
        .from('.lp-hero-sub, .lp-hero-actions', { y: 20, opacity: 0, duration: 0.8, stagger: 0.08 }, '-=0.8')
        .from('.lp-float', { y: 50, opacity: 0, duration: 1.1, stagger: 0.12 }, '-=1.1');
      const floats = gsap.utils.toArray<HTMLElement>('.lp-float').map((el, i) => gsap.to(el, { y: i % 2 ? 10 : -10, duration: 3 + i * 0.4, repeat: -1, yoyo: true, ease: 'sine.inOut', delay: 1.6 }));
      // Chuyển động lặp ở hero chỉ chạy khi hero còn trên màn hình.
      ScrollTrigger.create({ trigger: '.lp-hero', start: 'top bottom', end: 'bottom top', onToggle: self => floats.forEach(t => t.paused(!self.isActive)) });

      const splits = gsap.utils.toArray<HTMLElement>('.lp-split').map(el => {
        const split = SplitText.create(el, { type: 'words', mask: 'words', wordsClass: 'lp-w' });
        gsap.from(split.words, { yPercent: 135, duration: 0.9, ease: 'expo.out', stagger: 0.04, scrollTrigger: { trigger: el, start: 'top 85%', once: true } });
        // Từ khóa (phần trong <span>) được quét màu từ trái sang phải theo nhịp cuộn.
        const accent = el.querySelectorAll('span .lp-w');
        if (accent.length) gsap.fromTo(accent, { '--sweep': '0%' }, { '--sweep': '100%', ease: 'none', stagger: 0.35, scrollTrigger: { trigger: el, start: 'top 78%', end: 'top 36%', scrub: 0.5 } });
        return split;
      });
      gsap.utils.toArray<HTMLElement>('.lp-reveal').forEach(el => {
        gsap.from(el, { y: 44, opacity: 0, duration: 0.9, ease: 'power3.out', scrollTrigger: { trigger: el, start: 'top 88%', once: true } });
      });
      gsap.utils.toArray<HTMLElement>('.lp-stagger').forEach(group => {
        gsap.from(group.children, { y: 50, opacity: 0, duration: 0.9, ease: 'power3.out', stagger: 0.1, scrollTrigger: { trigger: group, start: 'top 85%', once: true } });
      });
      gsap.utils.toArray<HTMLElement>('.lp-fill').forEach(el => {
        gsap.fromTo(el.querySelectorAll(':scope > span'), { color: '#c4ccd6' }, { color: '#0f1d2b', stagger: 0.1, ease: 'none', scrollTrigger: { trigger: el, start: 'top 80%', end: 'bottom 55%', scrub: true } });
      });
      // Sơ đồ tự vẽ nét theo cuộn.
      // Lượt chạy thu nhỏ: tin nhắn vào → Robot nhận → ba thẻ bay ra từ Robot → thanh đọc chạy → bản trả lời ghép từng dòng.
      // Vị trí bay tính từ khung bọc (không có transform) nên chính xác; đo lại khi đổi cỡ.
      const sc = root.current?.querySelector<HTMLElement>('.lp-sc[data-live]');
      if (sc) {
        const bot = sc.querySelector<HTMLElement>('.is-bot')!;
        const from = (axis: 'x' | 'y') => (_: number, el: HTMLElement) => { const a = bot.getBoundingClientRect(), b = el.parentElement!.getBoundingClientRect(); return axis === 'x' ? a.left + a.width / 2 - (b.left + b.width / 2) : a.top + a.height / 2 - (b.top + b.height / 2); };
        const stage = [0.06, 0.2, 0.5, 0.66, 0.93];
        gsap.timeline({ defaults: { ease: 'power2.out' }, // Ghim cảnh giữa màn hình trong ~2 màn hình cuộn để từng bước hiện ra chậm, thấy rõ thay đổi.
          scrollTrigger: { trigger: sc, start: 'center 52%', end: () => `+=${Math.round(window.innerHeight * 2)}`, pin: true, anticipatePin: 1, scrub: 0.8, invalidateOnRefresh: true,
          onUpdate: self => setValue(sceneStore, stage.filter(t => self.progress >= t).length) } })
          .fromTo('.lp-sc-msg', { x: -70, opacity: 0 }, { x: 0, opacity: 1, duration: 0.6 }, 0)
          .fromTo('.lp-sc-agent', { x: from('x'), y: from('y'), scale: 0.35, opacity: 0 }, { x: 0, y: 0, scale: 1, opacity: 1, duration: 1, stagger: 0.18, ease: 'back.out(1.2)' }, 0.75)
          .fromTo('.lp-sc-read i', { width: '0%' }, { width: '100%', duration: 0.9, stagger: 0.12, ease: 'none' }, 2.1)
          .fromTo('.lp-sc-ans', { x: 60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.6 }, 2.9)
          .fromTo('.lp-sc-line', { opacity: 0, x: -14 }, { opacity: 1, x: 0, duration: 0.35, stagger: 0.25 }, 3.3)
          .fromTo('.lp-sc-done', { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.3 }, 4.2);
      }
      gsap.from('.lp-case', { y: 90, rotationX: 14, opacity: 0, transformPerspective: 1200, duration: 1.1, ease: 'power3.out', stagger: 0.1, clearProps: 'transform,opacity', scrollTrigger: { trigger: '.lp-cases-grid', start: 'top 82%', once: true } });

      if (wide) {
        // Khung tối nở từ thẻ bo góc ra toàn màn hình, rồi hiện từng dòng.
        const film = gsap.timeline({ scrollTrigger: { trigger: '.lp-film', start: 'top top', end: '+=1800', pin: true, scrub: 0.6, anticipatePin: 1, onEnter: () => sfx.swell() } });
        // Chỉ dùng transform/opacity (GPU); clip-path bo góc và blur chữ lớn buộc vẽ lại cả màn hình mỗi khung hình nên giật.
        film.fromTo('.lp-night', { scale: 0.84, borderRadius: 36 }, { scale: 1.06, borderRadius: 36, duration: 1, ease: 'none' })
          .from('.lp-night-line:not(.is-accent)', { opacity: 0, y: 50, stagger: 0.45, duration: 0.8 }, 0.1)
          .from('.lp-night-line.is-accent', { opacity: 0, y: 50, duration: 0.8 }, 0.95)
          .fromTo('.lp-night-glow', { scale: 0.7, opacity: 0.3 }, { scale: 1.4, opacity: 1, duration: 2.2 }, 0)
          .to({}, { duration: 0.9 });
        // Chồng tài liệu là vật thể xuyên suốt bốn chương; giấy rơi vào khung ngay khi cảnh hiện lên.
        const stage = root.current?.querySelector<HTMLElement>('.v4-paper-stage');
        if (stage) {
          const sheets = gsap.utils.toArray<HTMLElement>('.v4-sheet', stage);
          const W = () => stage.clientWidth, H = () => stage.clientHeight;
          const jit = (i: number, k: number) => ((i * 37 + k * 11) % 21) - 10;
          const tray = { db: 20, api: 50, sec: 80 } as Record<string, number>;
          const count: Record<string, number> = {};
          const sorted = PAPERS.map(p => { count[p.kind] = (count[p.kind] ?? 0) + 1; return count[p.kind] - 1; });
          gsap.fromTo(sheets, { x: (i: number) => W() * jit(i, 1) / 100, y: () => -H() * 0.9, rotation: (i: number) => jit(i, 2) * 4, opacity: 0 },
            { x: (i: number) => W() * jit(i, 3) / 120, y: (i: number) => H() * (jit(i, 4) / 160 + 0.18), rotation: (i: number) => jit(i, 5) * 1.6, opacity: 1, stagger: 0.03, ease: 'power3.out',
              scrollTrigger: { trigger: '.v4-paper', start: 'top 85%', end: 'top 15%', scrub: 0.8, invalidateOnRefresh: true, onEnter: () => sfx.paper(5) } });
          // Chương 1 đã bật sẵn nên chữ không có lúc "đổi chương" để hiện: cho chữ hiện theo cuộn, cùng nhịp với giấy rơi (CSS đọc --p0).
          gsap.fromTo('.v4-paper-copy', { '--p0': 0 }, { '--p0': 1, ease: 'none', scrollTrigger: { trigger: '.v4-paper', start: 'top 85%', end: 'top 15%', scrub: 0.8, invalidateOnRefresh: true } });
          const tabBars = gsap.utils.toArray<HTMLElement>('.v4-tabs b');
          gsap.timeline({ defaults: { ease: 'power2.inOut' }, scrollTrigger: {
            trigger: '.v4-paper', start: 'top top', end: '+=4000', pin: true, scrub: 0.8, anticipatePin: 1, invalidateOnRefresh: true,
            onUpdate: self => {
              const p = self.progress * 4;
              setValue(pchStore, p < 1 ? 0 : p < 2.2 ? 1 : p < 3.25 ? 2 : 3);
              tabBars.forEach((b, i) => gsap.set(b, { scaleX: gsap.utils.clamp(0, 1, p - i) }));
            },
          } })
            .fromTo('.v4-device', { rotationY: -24, rotationX: 10 }, { rotationY: -9, rotationX: 4, duration: 2, ease: 'none' }, 0)
            .fromTo('.v4-floor', { scaleX: 0.82, opacity: 0.55 }, { scaleX: 1, opacity: 1, duration: 2, ease: 'none' }, 0)
            // Chương 1: tài liệu lần lượt bị nạp vào màn hình, thanh ngữ cảnh đầy dần.
            .to(sheets, { x: () => W() * 0.2, y: () => -H() * 0.08, scale: 0.3, rotation: 0, opacity: 0, stagger: 0.045, duration: 0.45, ease: 'power2.in' }, 0.05)
            .fromTo('.v4-scr-docs li:nth-child(n+3)', { opacity: 0, x: 18 }, { opacity: 1, x: 0, stagger: 0.08, duration: 0.3 }, 0.15)
            .fromTo('.v4-meter b i', { scaleX: 0.18 }, { scaleX: 0.74, duration: 0.8, ease: 'none' }, 0.1)
            // Câu trả lời tự gõ ra trong lúc tài liệu được nạp: trôi chảy.
            .fromTo('.v4-ans-line', { clipPath: 'inset(0% 100% 0% 0%)' }, { clipPath: 'inset(0% 0% 0% 0%)', stagger: 0.2, duration: 0.28, ease: 'none' }, 0.3)
            // Chương 2: quá tải — tài liệu tràn ra khỏi màn hình.
            .to('.v4-meter b i', { scaleX: 1, duration: 0.4 }, 1.05)
            // Chương 2: từng câu bị gắn cờ không rõ nguồn.
            .fromTo('.v4-flag', { opacity: 0, scale: 0.5 }, { opacity: 1, scale: 1, stagger: 0.12, duration: 0.22, ease: 'back.out(2.4)' }, 1.35)
            .fromTo('.v4-alert', { opacity: 0, y: 16, scale: 0.9 }, { opacity: 1, y: 0, scale: 1, duration: 0.25, ease: 'back.out(2)' }, 1.6)
            .to('.v4-alert', { opacity: 0, y: -12, duration: 0.15 }, 2.0)
            .to(sheets, { x: (i: number) => W() * (((i * 53) % 110) - 55) / 100, y: (i: number) => H() * (((i * 29) % 96) - 48) / 100, rotation: (i: number) => jit(i, 7) * 2.6, scale: 0.9, opacity: 1, duration: 0.8, stagger: 0.015, ease: 'power3.out' }, 1.1)
            .fromTo('.v4-dark', { clipPath: 'inset(0% 0% 100% 0%)' }, { clipPath: 'inset(0% 0% 0% 0%)', duration: 0.5, ease: 'none' }, 2.0)
            // Nền tối loang ra từ tờ kế hoạch (shader); lớp .v4-dark ở trên chỉ dùng khi máy không có WebGL.
            .fromTo(storyFx, { dark: 0 }, { dark: 1, duration: 0.55, ease: 'power1.inOut' }, 1.88)
            .fromTo('.v4-scan', { top: '0%', opacity: 1 }, { top: '100%', duration: 0.5, ease: 'none' }, 2.0)
            .to('.v4-scan', { opacity: 0, duration: 0.05 }, 2.5)
            .to('.v4-device-wrap', { opacity: 0, scale: 0.86, y: -24, duration: 0.35 }, 2.05)
            .fromTo('.v4-tray', { opacity: 0, y: 40 }, { opacity: 1, y: 0, stagger: 0.08, duration: 0.35 }, 2.35)
            .fromTo('.v4-note', { opacity: 0, scale: 0.6, rotation: -12 }, { opacity: 1, scale: 1, rotation: -3, duration: 0.35, ease: 'back.out(1.6)' }, 2.6)
            .fromTo('.v4-budget i', { scaleX: 0 }, { scaleX: 1, stagger: 0.08, duration: 0.35, ease: 'power2.out' }, 2.8)
            .to(sheets, {
              x: (i: number) => { const k = PAPERS[i].kind; return k === 'noise' ? W() * (i % 2 ? 0.6 : -0.6) : k === 'shared' ? W() * (sorted[i] ? 0.15 : -0.15) : W() * ((tray[k] - 50) / 100 + sorted[i] * 0.012); },
              y: (i: number) => { const k = PAPERS[i].kind; return k === 'noise' ? -H() * 0.2 : k === 'shared' ? -H() * 0.29 : H() * (0.25 - sorted[i] * 0.022); },
              rotation: (i: number) => PAPERS[i].kind === 'noise' ? jit(i, 9) * 6 : jit(i, 8) * 0.4,
              opacity: (i: number) => PAPERS[i].kind === 'noise' ? 0 : 1, scale: 0.82, duration: 0.6, stagger: 0.02,
            }, 2.5)
            // Chương 4: mọi tờ giấy thu về giữa, gom thành bản tổng hợp.
            .to(sheets, { x: 0, y: 0, scale: 0.5, rotation: 0, opacity: 0, duration: 0.4, stagger: 0.012 }, 3.22)
            .fromTo('.v4-ring-cap', { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.25 }, 3.5)
            .to('.v4-tray, .v4-note', { opacity: 0, duration: 0.25 }, 3.25)
            .fromTo('.v4-report', { opacity: 0, scale: 0.7, xPercent: -50, yPercent: -50, y: 30 }, { opacity: 1, scale: 1, xPercent: -50, yPercent: -50, y: 0, duration: 0.3, ease: 'back.out(1.4)' }, 3.3)
            .fromTo('.v4-report li', { opacity: 0, x: -12 }, { opacity: 1, x: 0, stagger: 0.06, duration: 0.18 }, 3.42)
            .to({}, { duration: 0.2 }, 4);
        }
        // Ba tác tử: thẻ sau trượt lên phủ thẻ trước, thẻ trước lùi xa và mờ dần.
        const cards = gsap.utils.toArray<HTMLElement>('.lp-stack-card');
        const last = cards[cards.length - 1];
        cards.forEach((card, i) => {
          if (card === last) return;
          ScrollTrigger.create({ trigger: card, start: `top ${96 + i * 26}px`, endTrigger: last, end: `top ${96 + (cards.length - 1) * 26}px`, pin: true, pinSpacing: false });
          gsap.to(card, { scale: 1 - (cards.length - 1 - i) * 0.05, opacity: 0.72, ease: 'none',
            scrollTrigger: { trigger: cards[i + 1], start: 'top bottom', end: `top ${96 + (i + 1) * 26}px`, scrub: true, onEnter: () => sfx.whoosh() } });
        });
        // Tám bước: cột trái đứng yên, vạch tiến độ chạy theo cuộn, bước tới đâu sáng tới đó.
        ScrollTrigger.create({ trigger: '.lp-rail', start: 'top 120px', end: () => `bottom ${120 + (root.current?.querySelector<HTMLElement>('.lp-rail-side')?.offsetHeight ?? 0)}px`, pin: '.lp-rail-side', pinSpacing: false, invalidateOnRefresh: true });
      }
      gsap.fromTo('.lp-rail-line b', { scaleY: 0 }, { scaleY: 1, ease: 'none', scrollTrigger: { trigger: '.lp-rail-steps', start: 'top 62%', end: 'bottom 62%', scrub: true } });
      const railSteps = gsap.utils.toArray<HTMLElement>('.lp-rail-step');
      // Như kéo thanh độ sáng: một giá trị --b (0..1) chạy đều theo cuộn, nền và mọi lớp phụ thuộc vào nó cùng sáng lên.
      // --b là biến kế thừa: mỗi lần đổi, trình duyệt tính lại style cho cả phần. Làm tròn tới 2% (mỗi nấc lệch 0,4% độ sáng, mắt không phân biệt được)
      // nên chỉ ghi khi thật sự đổi, thay vì ghi ở mỗi khung hình.
      const runEl = root.current?.querySelector<HTMLElement>('#mot-luot-chay');
      const bright = { b: 0 }; let lastB = -1;
      gsap.to(bright, { b: 1, ease: 'none', scrollTrigger: { trigger: '.lp-rail-steps', start: 'top 62%', end: 'bottom 62%', scrub: 0.6 },
        onUpdate: () => { const v = Math.round(bright.b * 50) / 50; if (v !== lastB) { lastB = v; runEl?.style.setProperty('--b', String(v)); } } });
      // Phần kêu gọi cuối trang: ký tự lật lên lần lượt, rồi đoạn mô tả, nút và ba biểu tượng; vầng sáng nở theo cuộn.
      gsap.timeline({ scrollTrigger: { trigger: '.lp-cta', start: 'top 72%', once: true, onEnter: () => document.querySelector('.lp-cta')?.classList.add('is-in') } })
        .from('.lp-cta-title .lp-ch', { yPercent: 115, opacity: 0, rotateX: -75, transformOrigin: '50% 100%', stagger: 0.022, duration: 0.95, ease: 'expo.out' })
        .from('.lp-cta-inner > p', { y: 18, opacity: 0, duration: 0.6 }, '-=0.6')
        .from('.lp-cta .lp-hero-actions > *', { y: 22, opacity: 0, scale: 0.92, stagger: 0.08, duration: 0.6, ease: 'back.out(1.8)', clearProps: 'transform,opacity' }, '-=0.4');
      gsap.fromTo('.lp-night-glow.is-cta', { xPercent: -50, yPercent: -50, scale: 0.7, opacity: 0.35 }, { xPercent: -50, yPercent: -50, scale: 1.3, opacity: 1, ease: 'none', scrollTrigger: { trigger: '.lp-cta', start: 'top bottom', end: 'bottom bottom', scrub: true } });
      // Chân trang: các chữ của tên thương hiệu trồi lên lần lượt.
      gsap.from('.lp-footer-mark span', { yPercent: 105, duration: 1.1, ease: 'expo.out', stagger: 0.045, scrollTrigger: { trigger: '.lp-footer-marks', start: 'top 96%', once: true } });
      railSteps.forEach(el => gsap.from(el, { y: 70, opacity: 0, duration: 0.9, ease: 'power3.out', clearProps: 'transform,opacity', scrollTrigger: { trigger: el, start: 'top 92%', once: true } }));
      // Mỗi bước sáng từ lúc đầu nó qua mốc 62% đến khi bước kế tiếp tới mốc đó, không có khoảng trống giữa hai thẻ.
      railSteps.forEach((el, i) => ScrollTrigger.create({ trigger: el, start: 'top 62%', ...(railSteps[i + 1] ? { endTrigger: railSteps[i + 1], end: 'top 62%' } : { end: 'bottom 62%' }),
        onToggle: self => { el.classList.toggle('is-active', self.isActive); if (self.isActive) setValue(railStore, i); } }));
      return () => { splits.forEach(s => s.revert()); smoother?.kill(); };
    });
    return () => mm.revert();
  }, { scope: root, dependencies: [fullMotion, wide], revertOnUpdate: true });


  const lines = (text: string) => text.split('\n').map(t => <span className="lp-line" key={t}><span>{t}</span></span>);
  const fill = (text: string) => text.split(' ').map((w, i) => <span key={i}>{w} </span>);

  return <div className="lp" ref={root} data-motion={motionOn ? 'on' : 'off'} onClick={jump} onPointerOver={hoverSound}>
    <a className="lp-skip" href="#noi-dung">Đến nội dung chính</a>
    <header className="lp-header">
      <Link to="/" aria-label="OrchestrIQ Studio — trang chủ"><BrandLogo showSubtitle={false}/></Link>
      <nav className="lp-nav" aria-label="Điều hướng chính">{NAV.map(([href, label]) => <a key={href} href={href}>{label}</a>)}</nav>
      <div className="lp-header-actions">
        <button type="button" className={`lp-sound${soundOn ? ' is-on' : ''}`} aria-pressed={soundOn} aria-label={soundOn ? 'Tắt hiệu ứng âm thanh' : 'Bật hiệu ứng âm thanh'} title={soundOn ? 'Tắt âm thanh' : 'Bật âm thanh'} onClick={toggleSound}>
          {soundOn ? <Volume2 size={18}/> : <VolumeX size={18}/>}
        </button>
        <Link to="/login" className="lp-login">Đăng nhập</Link>
        <Link to="/studio" onClick={armIntro} className="lp-btn">Mở Studio <ArrowUpRight size={16}/></Link>
        <button className="lp-menu-btn" aria-label={menuOpen ? 'Đóng menu' : 'Mở menu'} aria-expanded={menuOpen} aria-controls="lp-mobile-nav" onClick={() => { sfx.tick(!menuOpen); setMenuOpen(!menuOpen); }}>{menuOpen ? <X size={22}/> : <Menu size={22}/>}</button>
      </div>
    </header>
    {menuOpen && <nav id="lp-mobile-nav" className="lp-mobile-nav" aria-label="Điều hướng di động">
      {NAV.map(([href, label]) => <a key={href} href={href} onClick={() => setMenuOpen(false)}>{label}<ArrowUpRight size={18}/></a>)}
      <Link to="/login" onClick={() => setMenuOpen(false)}>Đăng nhập<ArrowUpRight size={18}/></Link>
    </nav>}

    {videoOpen && <VideoDialog onClose={closeVideo}/>}

    <div className="lp-smooth"><div className="lp-smooth-content">
    <main id="noi-dung">
      <section className="lp-hero lp-wrap">
        <div className="lp-blobs" aria-hidden="true"><i/><i/></div>
        <div className="lp-hero-copy">
          <p className="lp-kicker"><i/>Nền tảng Multi-Agent LLM chạy cục bộ</p>
          <h1>{lines('Đúng nhiệm vụ.\nĐúng tri thức.')}</h1>
          <p className="lp-hero-script">
            cho từng tác tử AI.
            <svg className="lp-brush" viewBox="0 0 600 40" preserveAspectRatio="none" aria-hidden="true"><path d="M6 28 C 120 12, 260 10, 360 18 S 540 30, 594 14"/></svg>
          </p>
          <p className="lp-hero-sub">OrchestrIQ Studio chia một câu hỏi kỹ thuật cho ba tác tử chuyên môn. Mỗi tác tử chỉ đọc phần tài liệu nó cần, rồi kết quả được ghép thành một câu trả lời có thể kiểm tra lại. Tất cả chạy trên máy của bạn.</p>
          <div className="lp-hero-actions">
            <Link to="/studio" onClick={armIntro} className="lp-btn lp-btn-lg">Mở Studio <ArrowUpRight size={18}/></Link>
            <button type="button" className="lp-link lp-play-link" onClick={() => { setVideoOpen(true); sfx.tick(); }}><span><Play size={14} fill="currentColor"/></span>Xem video 1 phút</button>
          </div>
          {systemReduced && !fullMotion && <p className="lp-motion-notice">Thiết bị đang bật giảm chuyển động. <button type="button" onClick={() => setFullMotion(true)}>Bật hiệu ứng cho trang này</button></p>}
        </div>
        <div className="lp-hero-art" aria-hidden="true" onPointerMove={parallax}>
          <div className="lp-float lp-card lp-card-ghost" style={{ '--d': 0.4 } as React.CSSProperties}><span/><span/><span/><span/></div>
          <div className="lp-float lp-card lp-card-main" style={{ '--d': 1 } as React.CSSProperties}>
            <p className="lp-card-label">Yêu cầu</p>
            <p className="lp-card-q">Thiết kế luồng thanh toán không xử lý trùng, có kiểm soát quyền truy cập.</p>
            <div className="lp-card-split"><span>Đang phân rã</span><i/><span>3 nhiệm vụ</span></div>
          </div>
          {AGENTS.map(({ Icon, label, task, tone }, i) => <div key={tone} className={`lp-float lp-card lp-agent-card is-${tone}`} style={{ '--i': i, '--d': 1.6 + i * 0.3 } as React.CSSProperties}>
            <span className="lp-sa-icon"><Icon size={20}/></span>
            <div><strong>{label}</strong><span>{task}</span></div>
            <em>{['Đang đọc', 'Đang đọc', 'Chờ tài liệu'][i]}</em>
          </div>)}
          <div className="lp-float lp-hero-robot" style={{ '--d': 2.4 } as React.CSSProperties}><AssistantRobot size={210} interactive colorConfig={{ shell: '#14263a', trim: '#c9d7ee', screen: '#7fd3ff' }}/></div>
          <div className="lp-float lp-chip" style={{ '--d': 2 } as React.CSSProperties}>● Chạy cục bộ</div>
        </div>
      </section>

      <div className="lp-marquee" aria-hidden="true">
        <div className="lp-marquee-row">{[0, 1].map(c => <span key={c}>{MARQUEE.map(w => <em key={w}>{w}<i>✦</i></em>)}</span>)}</div>
      </div>

      <section className="lp-intro lp-wrap">
        <p className="lp-eyebrow lp-center">Cách OrchestrIQ làm việc</p>
        <h2 className="lp-fill lp-center" aria-label="Từ một câu hỏi đến câu trả lời có thể kiểm chứng.">{fill('Từ một câu hỏi đến câu trả lời có thể kiểm chứng.')}</h2>
        <p className="lp-center lp-intro-sub">Cuộn xuống để xem câu chuyện, từ vấn đề đến lời giải.</p>
        <RunScene key={pinned ? "live" : "static"} store={sceneStore} live={pinned}/>
        <div className="lp-teaser-wrap lp-reveal"><VideoTeaser onOpen={() => { setVideoOpen(true); sfx.tick(); }}><strong>Xem OrchestrIQ Studio trong 1 phút</strong><span>Video giới thiệu · khoảng 1 phút</span></VideoTeaser></div>
      </section>

      <section className="lp-film" aria-label="Một câu hỏi, ba chuyên gia, một câu trả lời">
        <div className="lp-night">
          <div className="lp-night-glow" aria-hidden="true"/>
          <div className="lp-night-grid" aria-hidden="true"/>
          <p className="lp-night-line">Một câu hỏi</p>
          <p className="lp-night-line">Ba chuyên gia</p>
          <p className="lp-night-line is-accent">Một câu trả lời</p>
        </div>
      </section>

      <section className="v4-paper" id="cau-chuyen" data-ch={pchStore.v} data-mode={pinned ? 'pin' : 'flow'}>
        {pinned ? <div className="v4-paper-inner">
          <div className="v4-dark" aria-hidden="true"/>
          <StorySky/>
          <div className="v4-scan" aria-hidden="true"/>
          <div className="v4-paper-copy" aria-live="polite">
            <ChapterCopy store={pchStore}/>
          </div>
          <PaperStage/>
          <ChapterTabs store={pchStore}/>
        </div> : <div className="lp-wrap v4-paper-flow">{PAPER_CHAPTERS.map((c, i) => <article key={c.tag} className="lp-reveal">
          <p className="v4-kicker">0{i + 1} — {c.tag}</p><h2>{c.title}</h2><p>{c.body}</p>
          <Flow v={(['overload', 'M', 'alloc', 'final'] as const)[i]}/>
        </article>)}</div>}
      </section>

      <section className="lp-agents-sec" id="chuyen-gia">
        <div className="lp-wrap">
          <div className="lp-sec-head">
            <div><p className="lp-eyebrow">Ba tác tử chuyên môn</p><h2 className="lp-big lp-split">Mỗi tác tử, <span className="is-hl">một góc nhìn.</span></h2></div>
            <p>Cùng chạy trên mô hình qwen3:4b, nhưng mỗi tác tử có nhiệm vụ, chỉ dẫn và phần tài liệu riêng. Nhờ vậy, chúng không giẫm lên phần việc của nhau.</p>
          </div>
          <div className="lp-stack">
            {AGENTS.map(({ Icon, label, name, tone, role, reads, gives, files }, i) => <article key={tone} className={`lp-stack-card is-${tone}`}>
              <div className="lp-stack-copy">
                <span className="lp-stack-index">0{i + 1} <i>/ 03</i></span>
                <div className="lp-stack-title"><span className="lp-persona-icon"><Icon size={28}/></span><div><h3>{label}</h3><small>{name}</small></div></div>
                <p className="lp-stack-role">{role}</p>
                <div className="lp-stack-reads"><span>Đọc</span><ul>{reads.map(r => <li key={r}>{r}</li>)}</ul></div>
              </div>
              <div className="lp-stack-desk" aria-hidden="true">
                {files.map((f, j) => <div key={f} className={`lp-desk-sheet is-${tone}`} style={{ '--j': j } as React.CSSProperties}><b>{f.split('.').pop()!.toUpperCase()}</b><span>{f}</span></div>)}
                <div className="lp-draft"><span className="lp-draft-head"><Icon size={14}/>Bản nháp của {label}</span><p>{gives}</p><i/><i/><i/></div>
              </div>
            </article>)}
          </div>
        </div>
      </section>

      <section className="lp-run" id="mot-luot-chay">
        <div className="lp-wrap lp-rail">
          <div className="lp-rail-side">
            <p className="lp-eyebrow">Bên trong một lượt chạy</p>
            <h2 className="lp-big lp-split">Tám bước, <span>không bước nào bị giấu.</span></h2>
            <p className="lp-rail-intro">Đây là đúng tám bước mà Studio hiển thị cho mỗi lượt điều phối. Bạn có thể mở từng bước để xem đầu vào và kết quả của nó.</p>
            <RailCount store={railStore}/>
          </div>
          <div className="lp-rail-steps">
            <span className="lp-rail-line" aria-hidden="true"><b/></span>
            {STEPS.map(({ Icon, title, body }, i) => <article key={title} className="lp-rail-step">
              <span className="lp-rail-dot" aria-hidden="true"><Icon size={15}/></span>
              <div className="lp-rail-text"><span className="lp-run-num">Bước {String(i + 1).padStart(2, '0')}</span><h3>{title}</h3><p>{body}</p></div>
              <RunArt k={i}/>
            </article>)}
          </div>
        </div>
      </section>

      <section className="lp-cases" id="kich-ban">
        <div className="lp-wrap">
          <div className="lp-sec-head">
            <div><p className="lp-eyebrow">Kịch bản ví dụ</p><h2 className="lp-big lp-split">Những câu hỏi Studio <span>được xây để trả lời.</span></h2></div>
            <p>Mỗi kịch bản chạm tới cả dữ liệu, API và bảo mật, đúng loại bài toán mà một tác tử đơn lẻ dễ bỏ sót.</p>
          </div>
          <div className="lp-cases-grid">
            {CASES.map(({ Icon, title, q, tags, tone, files }) => <article key={title} className={`lp-case is-${tone}`} onPointerMove={tilt} onPointerLeave={untilt}>
              <div className="lp-case-art">
                <span className="lp-case-icon"><Icon size={34}/></span>
                {files.map((f, j) => <div key={f} className="lp-case-sheet" style={{ '--j': j } as React.CSSProperties}><b>{f.split('.').pop()!.toUpperCase()}</b><span>{f}</span></div>)}
                <div className="lp-case-agents">{AGENTS.map(({ Icon: A, tone: t }) => <span key={t} className={`lp-sa-icon is-${t}`}><A size={15}/></span>)}</div>
              </div>
              <div className="lp-case-body">
                <h3>{title}</h3>
                <p><MessageSquareText size={16}/>{q}</p>
                <ul>{tags.map(t => <li key={t}>{t}</li>)}</ul>
              </div>
            </article>)}
          </div>
        </div>
      </section>

      <section className="lp-methods lp-wrap" id="phuong-phap">
        <div className="lp-sec-head">
          <div><p className="lp-eyebrow">Các điều kiện được so sánh</p><h2 className="lp-big lp-split">Cùng câu hỏi.<br/><span>Nhiều cách điều phối.</span></h2></div>
          <p>Để biết điều phối đầy đủ có thật sự giúp ích hay không, chúng tôi so sánh nó với các cách làm khác trên cùng mô hình, cùng tài liệu. Ba điều kiện này cũng là ba cách trả lời bạn chọn được trong Studio.</p>
        </div>
        <MethodsBox motionOn={motionOn}/>
      </section>

      <section className="lp-caps lp-wrap" id="kha-nang">
        <div className="lp-sec-head">
          <div><p className="lp-eyebrow">Khả năng</p><h2 className="lp-big lp-split">Phân tích sâu.<br/><span>Chạy cục bộ.</span><br/>Đo được.</h2></div>
          <p>Ba phần của Studio, cùng phục vụ một mục tiêu: hiểu một yêu cầu phần mềm từ nhiều góc nhìn mà không đánh đổi quyền kiểm soát dữ liệu.</p>
        </div>
        <div className="lp-caps-grid lp-bento lp-stagger">
          <article className="lp-cap">
            <div className="lp-cap-art lp-art-kb">
              <div className="lp-drop"><Upload size={18}/>Kéo thả tài liệu</div>
              {[['dac-ta-thanh-toan.md', 'API', 'api'], ['luoc-do-giao-dich.sql', 'Dữ liệu', 'db'], ['chinh-sach-bao-mat.md', 'Bảo mật', 'sec']].map(([f, t, k]) => <div key={f} className="lp-doc-row"><FileText size={16}/><span>{f}</span><em className={`is-${k}`}>{t}</em></div>)}
            </div>
            <h3>Kho tri thức của bạn</h3>
            <p>Nạp PDF, Markdown, SQL. Tài liệu được phân đoạn, gắn nhãn chuyên môn và lưu trong kho vector cục bộ.</p>
          </article>
          <article className="lp-cap">
            <div className="lp-cap-art lp-art-flow">
              <span className="lp-node is-q">Yêu cầu</span>
              <svg viewBox="0 0 300 160" aria-hidden="true"><path d="M150 30 C150 60 50 60 50 80 M150 30 V80 M150 30 C150 60 250 60 250 80 M50 108 C50 130 150 130 150 140 M150 108 V140 M250 108 C250 130 150 130 150 140"/></svg>
              <div className="lp-nodes">{AGENTS.map(({ Icon, tone }) => <span key={tone} className={`lp-sa-icon is-${tone}`}><Icon size={18}/></span>)}</div>
              <span className="lp-node is-a">Tổng hợp</span>
            </div>
            <h3>Điều phối đa tác tử</h3>
            <p>Phân rã yêu cầu, giao việc theo chuyên môn, cấp đúng ngữ cảnh rồi tổng hợp. Từng bước đều có dấu vết.</p>
          </article>
          <article className="lp-cap">
            <div className="lp-cap-art lp-art-lab">
              {[['A', 'Vanilla RAG'], ['B', 'Multi-Agent cơ bản'], ['C', 'Điều phối đầy đủ']].map(([k, t]) => <div key={k} className={`lp-lab-row${k === 'C' ? ' is-a' : ''}`}><b>{k}</b><span>{t}</span><em>Chờ đo</em></div>)}
            </div>
            <h3>Phòng thực nghiệm</h3>
            <p>Chạy cùng câu hỏi qua các điều kiện A, B, C. Ô nào chưa có số đo thật sẽ ghi rõ là chưa đo.</p>
          </article>
          <article className="lp-cap is-wide">
            <div className="lp-cap-art lp-art-stack">
              <span className="lp-stack-laptop"><Laptop size={20}/>Máy của bạn</span>
              {[['Giao diện', 'React'], ['Điều phối', 'FastAPI'], ['Kho vector', 'Qdrant'], ['Mô hình', 'Ollama · Qwen3:4b']].map(([t, d], i) => <div key={t} className="lp-layer" style={{ '--i': i } as React.CSSProperties}><strong>{t}</strong><span>{d}</span></div>)}
            </div>
            <h3>Chạy trọn trên một máy</h3>
            <p>Bốn lớp của hệ thống nằm trên máy của bạn. Luồng phân tích gọi mô hình qua Ollama cục bộ.</p>
          </article>
          <article className="lp-cap is-wide">
            <div className="lp-cap-art lp-art-trace">
              <span className="lp-trace-head"><ScrollText size={16}/>Nhật ký lượt chạy</span>
              {[['planner', 'success', 'ok'], ['t1 · Dữ liệu', 'success', 'ok'], ['t2 · API', 'length · giữ lại', 'warn'], ['t3 · Bảo mật', 'success', 'ok'], ['tổng hợp', 'success', 'ok']].map(([c, st, k], i) => <div key={c} className="lp-trace-row" style={{ '--i': i } as React.CSSProperties}><span>{c}</span><em className={`is-${k}`}>{st}</em><b>token từ Ollama</b></div>)}
            </div>
            <h3>Truy vết từng lượt</h3>
            <p>Mọi lần gọi mô hình đều được ghi, kể cả lần lỗi. Lượt chạy lưu kèm cấu hình để đối chiếu sau.</p>
          </article>
        </div>
      </section>

      <section className="lp-tech" aria-label="Công nghệ nền tảng">
        <p className="lp-eyebrow lp-center">Công nghệ nền tảng</p>
        {[0, 1].map(row => <div key={row} className={`lp-tech-row${row ? ' is-rev' : ''}`} aria-hidden={row === 1}>
          {[0, 1].map(c => <span key={c}>{(row ? [...STACK].reverse() : STACK).map(([n, d]) => <em key={n}><b>{n}</b>{d}</em>)}</span>)}
        </div>)}
      </section>

      <section className="lp-mission" id="nghien-cuu">
        <div className="lp-wrap">
          <p className="lp-eyebrow">Nghiên cứu</p>
          <h2 className="lp-big lp-split">Hiệu quả cần được đo,<br/><span className="is-hl">không chỉ được hứa hẹn.</span></h2>
          <div className="lp-mission-rows">
            <div><span className="lp-mission-tag">Mục tiêu</span><p className="lp-fill" aria-label="Kiểm chứng bằng thực nghiệm việc phân bổ ngữ cảnh theo nhiệm vụ ảnh hưởng thế nào tới chất lượng, độ trễ và chi phí.">{fill('Kiểm chứng bằng thực nghiệm việc phân bổ ngữ cảnh theo nhiệm vụ ảnh hưởng thế nào tới chất lượng, độ trễ và chi phí.')}</p></div>
            <div><span className="lp-mission-tag">Cam kết</span><p className="lp-fill" aria-label="Không công bố con số nào chưa đo. Mọi lượt chạy, kể cả lượt lỗi, đều được giữ lại.">{fill('Không công bố con số nào chưa đo. Mọi lượt chạy, kể cả lượt lỗi, đều được giữ lại.')}</p></div>
          </div>
        </div>
      </section>

      <section className="lp-faq lp-wrap" id="hoi-dap">
        <div><p className="lp-eyebrow">Hỏi đáp</p><h2 className="lp-big lp-split">Trước khi<br/>bắt đầu.</h2></div>
        <div>{FAQS.map(([q, a]) => <details key={q} onToggle={e => sfx.tick(e.currentTarget.open)}><summary>{q}<span aria-hidden="true">+</span></summary><p>{a}</p></details>)}</div>
      </section>

      <section className="lp-cta" onPointerMove={ctaMove} onPointerLeave={ctaLeave}>
        <div className="lp-night-glow is-cta" aria-hidden="true"/>
        <div className="lp-night-grid" aria-hidden="true"/>
        <div className="lp-cta-spot" aria-hidden="true"/>
        <div className="lp-orbit" aria-hidden="true">{AGENTS.map(({ Icon, tone, label }, i) => <span key={tone} className={`lp-orbit-item is-${tone}`} style={{ '--i': i, '--d': [1, 1.7, 0.8][i] } as React.CSSProperties}><Icon size={22}/><em>{label}</em></span>)}</div>
        <div className="lp-wrap lp-cta-inner">
          <CtaTitle onRipple={ctaRipple}/>
          <p>Nạp tài liệu dự án, đặt một câu hỏi và xem ba tác tử phối hợp.</p>
          <div className="lp-hero-actions"><Link to="/studio" onClick={armIntro} className="lp-btn lp-btn-lg lp-btn-light" onPointerMove={magnet} onPointerLeave={unmagnet}>Mở Studio <ArrowUpRight size={18}/></Link><Link to="/login" className="lp-link" onPointerMove={magnet} onPointerLeave={unmagnet}>Đăng nhập <ArrowRight size={16}/></Link></div>
        </div>
      </section>
    </main>

    <footer className="lp-footer" onPointerMove={footMove}>
      <div className="lp-footer-spot" aria-hidden="true"/>
      <div className="lp-wrap lp-footer-grid">
        <div className="lp-footer-brand"><BrandLogo theme="dark"/><p>Điều phối thích ứng cho hệ thống Multi-Agent LLM, chạy trọn trên máy của bạn.</p></div>
        <nav aria-label="Liên kết chân trang"><strong>Khám phá</strong>{NAV.map(([href, label]) => <a key={href} href={href} className="lp-flink">{label}</a>)}</nav>
        <div><strong>Bắt đầu</strong><Link to="/studio" onClick={armIntro} className="lp-flink">Không gian làm việc</Link><Link to="/login" className="lp-flink">Đăng nhập</Link>
          <button type="button" className="lp-motion-setting" aria-pressed={fullMotion} onClick={() => setFullMotion(value => !value)}>{fullMotion ? 'Hiệu ứng: đầy đủ' : 'Hiệu ứng: theo thiết bị'}</button></div>
        <div><strong>Hỗ trợ</strong><a href="#hoi-dap" className="lp-flink">Câu hỏi thường gặp</a><Link to="/register" className="lp-flink">Tạo tài khoản</Link></div>
      </div>
      {/* Tên thương hiệu cỡ lớn khép trang: lớp nền mờ, lớp sáng chỉ hiện quanh con trỏ */}
      <div className="lp-footer-marks" aria-hidden="true">
        {['', ' is-lit'].map(k => <div key={k} className={`lp-footer-mark${k}`}>{[...'OrchestrIQ'].map((c, i) => <span key={i}>{c}</span>)}</div>)}
      </div>
      <div className="lp-wrap lp-footer-bottom">
        <span>© 2026 OrchestrIQ Studio</span>
        <a href="#noi-dung" className="lp-totop" aria-label="Về đầu trang" onPointerMove={magnet} onPointerLeave={unmagnet}><ArrowUp size={18}/></a>
      </div>
    </footer>
    </div></div>
  </div>;
}
