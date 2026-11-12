import { useEffect, useState } from 'react';
import { AssistantRobot } from '../robot/AssistantRobot';

// Nửa trái trang tài khoản. Phối màu 60/30/10: nền trang sáng trung tính, nửa trái màu mực thương hiệu,
// điểm nhấn là giấy ghi chú vàng và nhãn màu tài liệu. Hình ảnh lấy từ câu chuyện ở landing:
// những tờ tài liệu trên bàn, tờ ghi chú kế hoạch và Robot C27. Không phát sáng, không chuyển sắc.
const SHEETS = [
  { ext: 'SQL', tone: 'db', name: 'Thiết kế dữ liệu' },
  { ext: 'MD', tone: 'api', name: 'Đặc tả thanh toán' },
  { ext: 'MD', tone: 'sec', name: 'Chính sách bảo mật' },
];

export function AuthBrandSide({ quote = 'Phân rã yêu cầu, khám phá tri thức và đối chiếu kết quả trong một không gian làm việc.' }: { quote?: string }) {
  // Robot nhắm mắt khi người dùng gõ mật khẩu (sự kiện từ AuthPageFrame); trạng thái đặt qua prop nên không bị thao tác chuột đánh thức.
  const [pw, setPw] = useState(false);
  useEffect(() => { const on = (e: Event) => setPw((e as CustomEvent<boolean>).detail); window.addEventListener('auth-password-focus', on); return () => window.removeEventListener('auth-password-focus', on); }, []);
  return <aside className="auth-brand-panel">
    <div className="auth-brand-heading"><span className="auth-project-label">OrchestrIQ Studio</span><h2>Từ tri thức chung.<br/><span>Đến lời giải có cơ sở.</span></h2><p>{quote}</p></div>
    <div className="auth-desk" aria-hidden="true">
      {SHEETS.map((s, i) => <div key={s.name} className={`auth-sheet is-${s.tone}`} style={{ '--i': i } as React.CSSProperties}><b>{s.ext}</b><strong>{s.name}</strong><i/><i/><i/><i/></div>)}
      <div className="auth-note"><span/>Kế hoạch đã kiểm tra<small>3 nhiệm vụ · đủ nghĩa vụ</small></div>
      <div className="auth-robot-stage"><AssistantRobot size={150} interactive state={pw ? 'sleeping' : undefined} colorConfig={{ shell: '#22354d', trim: '#c9d7ee', screen: '#9cdcff' }}/></div>
    </div>
    <p className="auth-brand-footer">Multi-Agent RAG · chạy trên hạ tầng của bạn</p>
  </aside>;
}
