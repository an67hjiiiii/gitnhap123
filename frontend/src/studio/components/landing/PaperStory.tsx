import type { ReactNode } from 'react';
import { Database, Code2, Shield, FileText } from 'lucide-react';

// Cảnh "Chồng tài liệu" của landing. Mọi hình là minh họa cơ chế đã có trong mã, không phải số đo.
const TONES = ['db', 'api', 'sec'] as const;
const AGENT = { db: { Icon: Database, label: 'Dữ liệu' }, api: { Icon: Code2, label: 'API' }, sec: { Icon: Shield, label: 'Bảo mật' } };

export const PAPER_CHAPTERS: { tag: string; title: ReactNode; body: string }[] = [
  { tag: 'Thói quen', title: <>Ta tin câu trả lời của AI vì nó <i>trôi chảy</i>.</>, body: 'Dồn cả kho tài liệu vào một cửa sổ ngữ cảnh, mô hình vẫn viết ra một đoạn mạch lạc, đầy thuật ngữ.' },
  { tag: 'Rủi ro', title: <>Nhưng trôi chảy chưa chắc <i>có căn cứ</i>.</>, body: 'Phần trùng bị lặp, phần thừa chen vào, phần cần thiết rơi ra ngoài giới hạn ngữ cảnh. Không ai biết câu nào lấy từ đâu.' },
  { tag: 'Cách khác', title: <>OrchestrIQ chia tài liệu cho <i>đúng chuyên gia</i>.</>, body: 'Mỗi tác tử chỉ nhận phần của nhiệm vụ mình. Phần cả ba cùng cần được gom một lần thành ghi chú chung, giữ nguyên văn.' },
  { tag: 'Dấu vết', title: <>Mỗi kết quả giữ lại <i>sợi dây</i> về nguồn.</>, body: 'Kế hoạch, đoạn tài liệu đã cấp cho từng tác tử và mọi lần gọi mô hình đều được lưu để bạn tự kiểm tra.' },
];
// kind: tone của tài liệu; noise = không liên quan; shared = phần chung. Tên file là ví dụ.
type Kind = 'db' | 'api' | 'sec' | 'shared' | 'noise';
const NAMES: Record<Kind, string[]> = {
  db: ['luoc-do-giao-dich.sql', 'bang-payments.sql', 'khoa-idempotency.sql', 'chi-muc.sql'],
  api: ['dac-ta-thanh-toan.md', 'webhook-api.md'],
  sec: ['chinh-sach-bao-mat.md', 'phan-quyen-rbac.md', 'chu-ky-hmac.md', 'token-jwt.md'],
  shared: ['rang-buoc-chung.md', 'yeu-cau-goc.md'],
  noise: ['bien-ban-hop.pdf', 'ke-hoach-marketing.pdf', 'slide-gioi-thieu.pdf', 'faq-khach-hang.pdf'],
};
const KINDS: Kind[] = ['db', 'noise', 'api', 'shared', 'sec', 'db', 'noise', 'sec', 'shared', 'db', 'noise', 'sec', 'api', 'noise', 'sec', 'db'];
const seen: Partial<Record<Kind, number>> = {};
export const PAPERS = KINDS.map(kind => { const n = seen[kind] ?? 0; seen[kind] = n + 1; const name = NAMES[kind][n]; return { kind, name, ext: name.split('.').pop()!.toUpperCase() }; });

export function PaperStage() {
  return <div className="v4-paper-stage" aria-hidden="true">
    <div className="v4-device-wrap">
      <div className="v4-device">
        <div className="v4-screen">
          <div className="v4-scr-bar"><i/><i/><i/><span>Cửa sổ ngữ cảnh · qwen3:4b</span></div>
          <div className="v4-scr-main">
            <div className="v4-scr-chat">
              <p className="v4-scr-user">Thiết kế luồng thanh toán không xử lý trùng, có kiểm soát quyền.</p>
              <div className="v4-scr-ai"><b>AI</b><span><i/><i/><i/><i/></span></div>
            </div>
            <ul className="v4-scr-docs">{PAPERS.slice(0, 7).map(p => <li key={p.name} className={`is-${p.kind}`}><b>{p.ext}</b>{p.name}</li>)}</ul>
          </div>
          <div className="v4-meter"><span>Ngữ cảnh đã dùng</span><b><i/></b><em>Vượt giới hạn</em></div>
        </div>
        <div className="v4-glare"/>
      </div>
      <div className="v4-floor"/>
    </div>
    {TONES.map(t => { const { Icon, label } = AGENT[t]; return <div key={t} className={`v4-tray is-${t}`}><span className="v4-tray-head"><Icon size={15}/>{label}</span></div>; })}
    <div className="v4-note"><i/>Ghi chú chung<small>nguyên văn · có id nguồn</small></div>
    <svg className="v4-threads" viewBox="0 0 100 100" preserveAspectRatio="none">
      {[[20, 22], [80, 20], [14, 70], [86, 74], [50, 92]].map(([x, y], i) => <path key={i} d={`M50 50 Q ${(50 + x) / 2} ${y < 50 ? y - 6 : y + 6} ${x} ${y}`} pathLength={1}/>)}
    </svg>
    {[[20, 22], [80, 20], [14, 70], [86, 74], [50, 92]].map(([x, y], i) => <span key={i} className="v4-src" style={{ left: `${x}%`, top: `${y}%` }}><FileText size={12}/>{['luoc-do-giao-dich.sql', 'dac-ta-thanh-toan.md', 'chinh-sach-bao-mat.md', 'nhat-ky-luot-chay', 'cau-hinh · mã băm'][i]}</span>)}
    <div className="v4-report"><FileText size={18}/><div><strong>Bản thiết kế tổng hợp</strong><span>Dữ liệu · API · Bảo mật</span></div><em>Đã đối chiếu</em></div>
    {PAPERS.map((p, i) => <div key={i} className={`v4-sheet is-${p.kind}`}><b>{p.ext}</b><span>{p.name}</span></div>)}
  </div>;
}
