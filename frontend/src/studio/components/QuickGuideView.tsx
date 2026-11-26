// Hướng dẫn nhanh (Onboarding & Kịch bản mẫu): lộ trình 3 bước, ý nghĩa 3 mức bằng chứng, câu hỏi mẫu chạy ngay và bảng phím tắt.
import React from 'react';
import {
  ArrowRight,
  BookOpen,
  Bot,
  CheckCircle2,
  FolderOpen,
  HelpCircle,
  Keyboard,
  MessagesSquare,
  ShieldAlert,
  Sparkles,
  TriangleAlert,
} from 'lucide-react';
import type { NavigationTab } from '../types';
import { ToolHeader } from './analysis/shared';
import '../styles/pages-2b.css';

interface Props {
  docCount: number;
  onGo: (tab: NavigationTab) => void;
  onTryQuestion: (question: string) => void;
}

const STEPS: { num: string; title: string; desc: string; cta: string; tab: NavigationTab; Icon: typeof FolderOpen }[] = [
  {
    num: '01',
    title: 'Nạp tài liệu vào không gian làm việc',
    desc: 'Kéo thả PDF, Word, Excel, Markdown hoặc ảnh chụp văn bản. Hệ thống tự phân loại, chia đoạn thông minh và giữ nguyên dữ liệu trên máy chủ cục bộ.',
    cta: 'Mở kho Tài liệu',
    tab: 'library',
    Icon: FolderOpen,
  },
  {
    num: '02',
    title: 'Đặt câu hỏi đa ý hoặc gõ "/" gọi kỹ năng',
    desc: 'Hỏi tự nhiên bằng tiếng Việt, hoặc gõ "/" trong ô chat để gọi nhanh 14+ kỹ năng theo ngành (so sánh phiên bản, kiểm tra mâu thuẫn, rà soát hợp đồng…).',
    cta: 'Mở Không gian làm việc',
    tab: 'orchestration',
    Icon: MessagesSquare,
  },
  {
    num: '03',
    title: 'Đối chiếu nguồn trích dẫn & xem Văn phòng 3D',
    desc: 'Bấm trực tiếp vào từng thẻ nguồn để đọc đoạn gốc có tô sáng từ khóa, và mở Văn phòng Agent 3D để theo dõi đội tác tử phối hợp theo thời gian thực.',
    cta: 'Mở Văn phòng Agent',
    tab: 'office',
    Icon: Bot,
  },
];

const EVIDENCE_BADGES = [
  {
    tone: 'ok',
    title: 'Đủ bằng chứng (COMPLETE)',
    desc: 'Mọi ý trong câu hỏi đều có đoạn trích trực tiếp trong tài liệu. Số liệu, điều khoản đều gắn nguồn rõ ràng.',
    Icon: CheckCircle2,
  },
  {
    tone: 'warn',
    title: 'Một phần (PARTIAL)',
    desc: 'Tài liệu trả lời được một số ý, ý còn lại không có trong kho. Hệ thống tách bạch rõ phần có căn cứ và phần chưa đề cập.',
    Icon: TriangleAlert,
  },
  {
    tone: 'muted',
    title: 'Không có bằng chứng (NO_EVIDENCE)',
    desc: 'Tài liệu hiện tại không chứa thông tin để trả lời. Hệ thống từ chối trung thực thay vì tự suy diễn hay bịa số liệu.',
    Icon: ShieldAlert,
  },
];

const SAMPLE_PROMPTS = [
  'Tóm tắt các quy định quan trọng nhất và những điểm cần lưu ý trong bộ tài liệu hiện tại.',
  'Liệt kê đầy đủ các mốc thời gian, hạn mức và điều kiện áp dụng được nêu trong tài liệu.',
  'Đối chiếu quyền lợi và nghĩa vụ của các bên liên quan, ghi rõ trích dẫn theo từng mục.',
  'Có điểm nào chưa rõ ràng, còn thiếu hoặc dễ gây mâu thuẫn giữa các tài liệu đang mở không?',
];

export const QuickGuideView: React.FC<Props> = ({ docCount, onGo, onTryQuestion }) => {
  return (
    <main className="pg tl tone-overview guide">
      <div className="pg-col">
        <ToolHeader
          Icon={BookOpen}
          title="Hướng dẫn nhanh"
          desc="Làm chủ OrchestrIQ Studio trong 1 phút: quy trình 3 bước, cách đọc trạng thái bằng chứng, câu hỏi mẫu và phím tắt."
          right={
            <button type="button" className="btn btn-dark" onClick={() => onGo('orchestration')}>
              <MessagesSquare size={15} />Bắt đầu hỏi ngay
            </button>
          }
        />

        <section className="guide-steps" aria-label="Quy trình 3 bước">
          {STEPS.map(step => (
            <article key={step.num} className="dz-card guide-step">
              <div className="guide-step-top">
                <span className="guide-step-num">{step.num}</span>
                <span className="guide-step-ico" aria-hidden="true"><step.Icon size={18} /></span>
              </div>
              <h3>{step.title}</h3>
              <p>{step.desc}</p>
              <button type="button" className="btn btn-ghost is-sm" onClick={() => onGo(step.tab)}>
                {step.cta}<ArrowRight size={14} />
              </button>
            </article>
          ))}
        </section>

        <section className="dz-card guide-block" aria-label="Cách đọc 3 mức bằng chứng">
          <header className="guide-head">
            <HelpCircle size={18} />
            <div>
              <h2>Cách đọc 3 trạng thái bằng chứng (Trung thực khoa học)</h2>
              <p>Mỗi câu trả lời đều đi qua bước đối chiếu với đoạn trích gốc trong kho tri thức trước khi gửi cho bạn.</p>
            </div>
          </header>
          <div className="guide-badges">
            {EVIDENCE_BADGES.map(b => (
              <div key={b.title} className={`guide-badge is-${b.tone}`}>
                <span className="guide-badge-ico"><b.Icon size={17} /></span>
                <div>
                  <b>{b.title}</b>
                  <p>{b.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <div className="guide-two">
          <section className="dz-card guide-block" aria-label="Câu hỏi mẫu thử ngay">
            <header className="guide-head">
              <Sparkles size={18} />
              <div>
                <h2>Câu hỏi mẫu thử ngay</h2>
                <p>{docCount > 0 ? `Đang có ${docCount} tài liệu sẵn sàng — bấm một câu bên dưới để điền sẵn vào ô chat.` : 'Tải lên hoặc nạp bộ tài liệu mẫu rồi bấm thử các câu hỏi đa ý bên dưới.'}</p>
              </div>
            </header>
            <ul className="guide-prompts">
              {SAMPLE_PROMPTS.map(q => (
                <li key={q}>
                  <button type="button" onClick={() => onTryQuestion(q)}>
                    <span>{q}</span>
                    <ArrowRight size={15} />
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="dz-card guide-block" aria-label="Phím tắt và mẹo dùng nhanh">
            <header className="guide-head">
              <Keyboard size={18} />
              <div>
                <h2>Phím tắt & Mẹo làm việc nhanh</h2>
                <p>Thao tác mượt mà trên mọi màn hình không cần rời bàn phím.</p>
              </div>
            </header>
            <dl className="guide-keys">
              <div><dt><kbd>Ctrl K</kbd></dt><dd>Mở thanh Tìm nhanh: nhảy trang, nạp bộ mẫu hoặc mở lại hội thoại cũ</dd></div>
              <div><dt><kbd>/</kbd></dt><dd>Gõ ngay trong ô chat để gọi nhanh 14+ kỹ năng phân tích theo ngành</dd></div>
              <div><dt><kbd>Ctrl B</kbd></dt><dd>Thu gọn hoặc mở rộng thanh điều hướng bên trái</dd></div>
              <div><dt><kbd>Ctrl V</kbd></dt><dd>Dán trực tiếp ảnh chụp văn bản/bảng biểu vào ô chat để OCR và hỏi đáp</dd></div>
              <div><dt><kbd>Esc</kbd></dt><dd>Đóng nhanh hộp thoại, ngăn Lịch sử hoặc menu đang mở</dd></div>
            </dl>
          </section>
        </div>
      </div>
    </main>
  );
};
