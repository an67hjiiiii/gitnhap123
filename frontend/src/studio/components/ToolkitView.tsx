// Trang "Bộ công cụ <ngành>": mỗi ngành có bộ công cụ riêng theo nghiệp vụ của ngành đó (thẻ công cụ -> mở công cụ).
// Công cụ dùng chung (Hồ sơ tài liệu, Kiểm tra mâu thuẫn) nằm ở thanh bên, không lặp lại ở đây.
import React, { useState } from 'react';
import {
  ArrowLeft, ArrowRight, BookOpenText, Calculator, FileSignature, FileText, FolderCheck, GraduationCap, ListChecks, ListOrdered,
  MessageCircleQuestion, PencilRuler, Scale, SpellCheck, Users, Search, CheckCircle2, GitCompareArrows,
} from 'lucide-react';
import { ChecklistView, ChecklistMode } from './ChecklistView';
import { ConditionCheckView, ProcedureView } from './CaseworkViews';
import { ReqQualityView } from './ReqQualityView';
import { DesignView } from './DesignView';
import { RosterReview } from './tools/RosterReview';
import { QuizBuilder } from './tools/QuizBuilder';
import { RegulationLookup } from './tools/RegulationLookup';
import { PayCalculator } from './tools/PayCalculator';
import { RequestApproval } from './tools/RequestApproval';
import { PolicyFaq } from './tools/PolicyFaq';
import { ContractReview } from './tools/ContractReview';
import { DossierChecklist } from './tools/DossierChecklist';
import { DocumentValidity } from './tools/DocumentValidity';
import { Doc } from './analysis/shared';
import './casework.css';

type Props = { docs: Doc[]; workspaceId: number | string };
interface Tool { id: string; title: string; Icon: typeof Scale; what: string; when: string; render: (p: Props) => React.ReactNode }

const SOFTWARE_SOURCES: { mode: ChecklistMode; label: string }[] = [
  { mode: 'traceability', label: 'Yêu cầu có mã (FR-, NFR-…)' }, { mode: 'security', label: 'Bảo mật (OWASP ASVS)' }, { mode: 'criteria', label: 'Danh mục tự nhập' },
];
const SoftwareCriteria: React.FC<Props> = ({ docs, workspaceId }) => {
  const [source, setSource] = useState<ChecklistMode>('traceability');
  return <>
    <div className="tk-sources" role="radiogroup" aria-label="Nguồn tiêu chí"><span>Nguồn tiêu chí:</span>
      {SOFTWARE_SOURCES.map(s => <button key={s.mode} role="radio" aria-checked={source === s.mode} className={`chip${source === s.mode ? ' is-on' : ''}`} onClick={() => setSource(s.mode)}>{s.label}</button>)}</div>
    <ChecklistView key={`${source}-${workspaceId}`} mode={source} workspaceId={workspaceId} docs={docs} />
  </>;
};

const GENERAL_EXAMPLE = { question: 'Trường hợp này có đáp ứng điều kiện trong quy định không?', case: 'Mô tả các dữ kiện của trường hợp, kèm con số nếu có.', topic: 'Quy trình phê duyệt đề xuất' };

const TOOLS: Record<string, { tagline: string; tools: Tool[] }> = {
  education: { tagline: 'Dành cho phòng đào tạo, công tác sinh viên, giảng viên', tools: [
    { id: 'roster', title: 'Xét duyệt theo danh sách', Icon: Users, what: 'Tải bảng điểm, máy so từng sinh viên với ngưỡng trong quy chế.', when: 'Xét học bổng, tốt nghiệp, cảnh báo học tập cho cả lớp, cả khóa.', render: p => <RosterReview docs={p.docs} /> },
    { id: 'quiz', title: 'Tạo câu hỏi ôn tập', Icon: GraduationCap, what: 'Câu trắc nghiệm 4 phương án từ bài giảng, có đáp án và trích dẫn.', when: 'Ra đề ôn tập, kiểm tra nhanh, ngân hàng câu hỏi.', render: p => <QuizBuilder docs={p.docs} /> },
    { id: 'lookup', title: 'Tra cứu quy chế theo Điều', Icon: BookOpenText, what: 'Mục lục Chương, Điều và hỏi đáp trả về đúng Điều.', when: 'Trả lời sinh viên, tra quy định học vụ.', render: p => <RegulationLookup docs={p.docs} /> },
  ] },
  business_hr: { tagline: 'Dành cho phòng nhân sự, hành chính, quản lý', tools: [
    { id: 'pay', title: 'Tính phép năm, tiền làm thêm', Icon: Calculator, what: 'Lấy hệ số từ nội quy, máy tính ngày phép và tiền làm thêm giờ.', when: 'Chốt phép cuối năm, tính lương làm thêm hằng tháng.', render: p => <PayCalculator docs={p.docs} /> },
    { id: 'approval', title: 'Duyệt đơn từ', Icon: FileSignature, what: 'Kiểm đơn nghỉ phép, tạm ứng, mua sắm theo nội quy và chỉ ra cấp duyệt.', when: 'Trước khi trình ký một đơn.', render: p => <RequestApproval docs={p.docs} /> },
    { id: 'faq', title: 'Hỏi đáp chính sách', Icon: MessageCircleQuestion, what: 'Bộ câu hỏi thường gặp sinh từ nội quy, có trích dẫn.', when: 'Hội nhập nhân viên mới, đăng thông báo nội bộ.', render: p => <PolicyFaq docs={p.docs} /> },
  ] },
  legal_admin: { tagline: 'Dành cho pháp chế, văn thư, bộ phận một cửa', tools: [
    { id: 'contract', title: 'Rà soát hợp đồng', Icon: FileText, what: 'Kiểm nội dung chủ yếu theo Điều 398 BLDS 2015, chỉ ra điều khoản rủi ro.', when: 'Trước khi ký hoặc trình duyệt hợp đồng.', render: p => <ContractReview docs={p.docs} /> },
    { id: 'dossier', title: 'Hồ sơ thủ tục', Icon: FolderCheck, what: 'Danh mục giấy tờ cần nộp, đánh dấu đã có, các bước, thời hạn, lệ phí.', when: 'Chuẩn bị hoặc tiếp nhận hồ sơ.', render: p => <DossierChecklist docs={p.docs} /> },
    { id: 'validity', title: 'Hiệu lực văn bản', Icon: Scale, what: 'Số hiệu, ngày hiệu lực, văn bản đã bị thay thế trong kho.', when: 'Trước khi viện dẫn một văn bản.', render: p => <DocumentValidity docs={p.docs} /> },
  ] },
  software: { tagline: 'Dành cho phân tích nghiệp vụ, kiến trúc, kiểm thử phần mềm', tools: [
    { id: 'criteria', title: 'Rà soát theo tiêu chí', Icon: ListChecks, what: 'Đối chiếu yêu cầu có mã, tiêu chí OWASP ASVS hoặc danh mục tự nhập.', when: 'Kiểm thiết kế đã đáp ứng đặc tả chưa.', render: p => <SoftwareCriteria {...p} /> },
    { id: 'req_quality', title: 'Chất lượng yêu cầu', Icon: SpellCheck, what: 'Tìm yêu cầu viết mơ hồ, thiếu số đo, gộp ý (ISO/IEC/IEEE 29148).', when: 'Rà đặc tả trước khi chốt.', render: p => <ReqQualityView key={`rq-${p.workspaceId}`} workspaceId={p.workspaceId} docs={p.docs} /> },
    { id: 'design', title: 'Gói thiết kế', Icon: PencilRuler, what: 'Từ một yêu cầu ra thiết kế CSDL, API, bảo mật (SQL, OpenAPI nháp).', when: 'Bắt đầu thiết kế một tính năng.', render: p => <DesignView key={`ds-${p.workspaceId}`} workspaceId={p.workspaceId} docs={p.docs} /> },
  ] },
  general: { tagline: 'Dùng được với mọi loại quy định, quy trình', tools: [
    { id: 'procedure', title: 'Quy trình từng bước', Icon: ListOrdered, what: 'Các bước, ai làm, thời hạn, hồ sơ cần có, mỗi mục có trích dẫn.', when: 'Cần biết một việc phải làm theo thứ tự nào.', render: p => <ProcedureView docs={p.docs} example={GENERAL_EXAMPLE} /> },
    { id: 'conditions', title: 'Kiểm tra điều kiện', Icon: Scale, what: 'Một trường hợp có đủ điều kiện theo quy định không, từng điều kiện có căn cứ.', when: 'Trả lời câu hỏi "trường hợp này có được không?".', render: p => <ConditionCheckView docs={p.docs} example={GENERAL_EXAMPLE} /> },
    { id: 'criteria', title: 'Rà soát theo tiêu chí', Icon: ListChecks, what: 'Kiểm tài liệu theo danh mục tiêu chí của bạn.', when: 'Kiểm tài liệu có đủ các mục bắt buộc.', render: p => <ChecklistView key={`cr-${p.workspaceId}`} mode="criteria" workspaceId={p.workspaceId} docs={p.docs} /> },
  ] },
};

// Danh mục kỹ năng (Đợt 5): một danh mục chung lọc theo ngành, thay cho trang "Bộ công cụ <ngành>".
const CATEGORY: Record<string, string> = { education: 'Giáo dục', business_hr: 'Công ty', legal_admin: 'Văn phòng', software: 'Kỹ thuật', general: 'Chung' };
// kỹ năng gọi được ngay trong ô chat Tự động (bộ định tuyến chọn hoặc gõ "/")
const IN_CHAT: Record<string, string> = { procedure: 'procedure', conditions: 'conditions', quiz: 'quiz', validity: 'validity', contract: 'contract_review' };
// kỹ năng đã chạy thử thật trên giao diện ngày 20/11 (mô hình qwen3:4b); kỹ năng khác có kiểm thử nhưng chưa chạy lại trong đợt này
const RAN = new Set(['quiz', 'procedure', 'conditions', 'validity']);
const fold = (v: string) => v.normalize('NFD').replace(/\p{M}/gu, '').replace(/đ/gi, 'd').toLowerCase();

export const ToolkitView: React.FC<{ pack?: string | null; initialTool?: { pack: string; id: string } | null } & Props> = ({ pack, docs, workspaceId, initialTool }) => {
  const [cat, setCat] = useState<string>('all');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<{ pack: string; id: string } | null>(initialTool ?? null);
  React.useEffect(() => { if (initialTool) setOpen(initialTool); }, [initialTool?.pack, initialTool?.id]);
  const all = Object.entries(TOOLS).flatMap(([k, kit]) => kit.tools.map(t => ({ ...t, pack: k })))
    .filter((t, i, arr) => arr.findIndex(x => x.id === t.id) === i);  // "Rà soát theo tiêu chí" có ở hai ngành: hiện một lần
  const kit = open ? TOOLS[open.pack] : null;
  const tool = kit?.tools.find(t => t.id === open!.id);

  if (tool && open) return (
    <div className={`tk is-${open.pack}`}>
      <div className="tk-crumb">
        <button className="btn btn-ghost is-sm" onClick={() => setOpen(null)}><ArrowLeft size={15} />Danh mục kỹ năng</button>
        <nav className="tk-switch" aria-label="Chuyển kỹ năng cùng ngành">{kit!.tools.map(t => <button key={t.id} className={t.id === tool.id ? 'is-on' : ''} aria-current={t.id === tool.id ? 'page' : undefined} onClick={() => setOpen({ pack: open.pack, id: t.id })}><t.Icon size={15} />{t.title}</button>)}</nav>
      </div>
      {tool.render({ docs, workspaceId })}
    </div>
  );

  const k = fold(q.trim());
  const shown = all.filter(t => (cat === 'all' || t.pack === cat) && (!k || fold(`${t.title} ${t.what} ${t.when}`).includes(k)));
  const count = (c: string) => all.filter(t => c === 'all' || t.pack === c).length;
  return (
    <main className="pg tk tk-home tk-catalog">
      <div className="pg-col">
        <header className="tk-hero"><p className="tk-kicker">Danh mục kỹ năng</p><h1>Kỹ năng theo ngành</h1>
          <p>{all.length} kỹ năng dùng chung một kho tài liệu. Kỹ năng có nhãn "Trong ô chat" gọi được ngay khi hỏi, hoặc gõ "/" ở Không gian làm việc.</p>
          <div className="tk-filter">
            <nav className="tk-packs" aria-label="Lọc theo ngành">{['all', ...Object.keys(CATEGORY)].map(c => <button key={c} type="button" className={c === cat ? 'is-on' : ''} aria-pressed={c === cat} onClick={() => setCat(c)}>
              {c === 'all' ? 'Tất cả' : CATEGORY[c]} <em>{count(c)}</em></button>)}</nav>
            <label className="lib-find tk-find"><Search size={15} /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Tìm kỹ năng…" aria-label="Tìm kỹ năng" /></label>
          </div></header>
        {shown.length === 0 ? <p className="tk-note">Không có kỹ năng nào khớp “{q}”.</p> : <div className="tk-grid">{shown.map((t, i) => (
          <button key={t.id} className={`tk-card is-${t.pack}`} onClick={() => setOpen({ pack: t.pack, id: t.id })} style={{ animationDelay: `${i * 40}ms` }}>
            <span className="tk-ico"><t.Icon size={22} /></span>
            <span className="tk-tags"><i className="tk-cat">{CATEGORY[t.pack]}</i>{IN_CHAT[t.id] && <i className="tk-chat"><MessageCircleQuestion size={12} />Trong ô chat</i>}
              <i className={RAN.has(t.id) ? 'tk-ran' : 'tk-tested'} title={RAN.has(t.id) ? 'Có kiểm thử tự động và đã chạy thử thật trên giao diện 20/11' : 'Có kiểm thử tự động; chưa chạy lại thật trong đợt 20/11'}>
                <CheckCircle2 size={12} />{RAN.has(t.id) ? 'Đã chạy thật' : 'Có kiểm thử'}</i></span>
            <b>{t.title}</b><span className="tk-what">{t.what}</span>
            <span className="tk-when"><em>Dùng khi</em>{t.when}</span>
            <span className="tk-go">Mở kỹ năng <ArrowRight size={15} /></span>
          </button>))}
          <button className="tk-card is-legal_admin" onClick={() => window.dispatchEvent(new CustomEvent('oq-go', { detail: 'compare' }))}>
            <span className="tk-ico"><GitCompareArrows size={22} /></span>
            <span className="tk-tags"><i className="tk-cat">Văn phòng</i><i className="tk-chat"><MessageCircleQuestion size={12} />Trong ô chat</i><i className="tk-ran"><CheckCircle2 size={12} />Đã chạy thật</i></span>
            <b>So sánh phiên bản</b><span className="tk-what">Bản mới khác bản cũ ở Chương, Điều, Khoản nào: thêm, sửa, bỏ, giữ, di chuyển.</span>
            <span className="tk-when"><em>Dùng khi</em>Có quy chế, quy định, hợp đồng bản mới thay bản cũ.</span>
            <span className="tk-go">Mở trang So sánh <ArrowRight size={15} /></span>
          </button></div>}
        <p className="tk-note">Kết quả của các kỹ năng kèm trích dẫn đoạn tài liệu gốc; phép so sánh, tính toán và kết luận cuối do luật cố định thực hiện, mô hình chỉ đọc và trích thông tin.</p>
      </div>
    </main>
  );
};
