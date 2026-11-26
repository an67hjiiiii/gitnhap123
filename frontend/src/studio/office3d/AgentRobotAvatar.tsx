import type { CSSProperties } from 'react';
import { AGENT_PROFILES } from './agents';
import type { OfficeChatMood } from './liveDirector';
import type { AgentId } from './types';

/**
 * Bảng màu & nhận diện riêng cho 11 Agent (không trùng lặp giữa bất kỳ cặp Agent nào):
 * - RAG Specialist: Xanh Ngọc Lam (Cyan #0891b2) + Logo Kính lúp/Tài liệu
 * - Finance: Xanh Lá Rừng (Forest Emerald #15803d) + Logo Đồng xu tài chính
 * - Business: Nâu Đồng Ấm (#9a3412) + Logo Cặp doanh nhân
 */
export const AGENT_EYE_HEX: Record<AgentId, string> = {
  orchestrator: '#fbbf24',
  rag: '#22d3ee',
  analyst: '#60a5fa',
  reviewer: '#fb7185',
  integrator: '#c084fc',
  software: '#818cf8',
  business: '#fdba74',
  marketing: '#fb923c',
  hr: '#f472b6',
  finance: '#4ade80',
  education: '#e879f9',
};

/** 11 biểu tượng Logo vector riêng biệt (nét tinh gọn, dễ nhận diện ở cả cỡ nhỏ 11px lẫn lớn 22px). */
export function AgentRoleLogo({
  agentId,
  size = 12,
  color = 'currentColor',
}: {
  agentId: AgentId;
  size?: number;
  color?: string;
}) {
  const sw = 1.9;
  switch (agentId) {
    case 'orchestrator': // La bàn / Radar điều phối 4 hướng
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="6" stroke={color} strokeWidth={sw} />
          <path d="M10.8 5.2L9.2 9.2L5.2 10.8L6.8 6.8L10.8 5.2Z" fill={color} />
        </svg>
      );
    case 'rag': // Kính lúp rà kho tài liệu
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <circle cx="7" cy="7" r="4.3" stroke={color} strokeWidth={sw} />
          <path d="M10.3 10.3L13.8 13.8" stroke={color} strokeWidth={sw} strokeLinecap="round" />
          <path d="M5.4 7H8.6" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case 'analyst': // Biểu đồ cột số liệu
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <path d="M3 13V8.5M8 13V4M13 13V6.5" stroke={color} strokeWidth="2.2" strokeLinecap="round" />
          <path d="M2 13.5H14" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      );
    case 'reviewer': // Khiên dấu tích kiểm định QC
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <path d="M8 1.8L13 3.8V7.8C13 11 10.8 13.4 8 14.3C5.2 13.4 3 11 3 7.8V3.8L8 1.8Z" stroke={color} strokeWidth={sw} strokeLinejoin="round" />
          <path d="M5.6 8.1L7.3 9.8L10.7 6.3" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'integrator': // Chồng lớp tổng hợp đầu ra
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <path d="M8 2.2L13.8 5.4L8 8.6L2.2 5.4L8 2.2Z" stroke={color} strokeWidth={sw} strokeLinejoin="round" />
          <path d="M2.6 8.6L8 11.6L13.4 8.6" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" />
          <path d="M2.6 11.4L8 14.2L13.4 11.4" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'software': // Ngoặc mã nguồn </>
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <path d="M5.5 4.5L2.2 8L5.5 11.5M10.5 4.5L13.8 8L10.5 11.5M9.1 3.4L6.9 12.6" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'business': // Cặp doanh nhân / Chiến lược
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <rect x="2.2" y="5" width="11.6" height="8.2" rx="2" stroke={color} strokeWidth={sw} />
          <path d="M5.6 5V3.7C5.6 3 6.2 2.5 6.9 2.5H9.1C9.8 2.5 10.4 3 10.4 3.7V5" stroke={color} strokeWidth={sw} />
          <path d="M2.5 8.8H13.5" stroke={color} strokeWidth="1.4" />
        </svg>
      );
    case 'marketing': // Loa chiến dịch truyền thông
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <path d="M3 9.5V6.5L11.8 3.2V12.8L3 9.5Z" stroke={color} strokeWidth={sw} strokeLinejoin="round" />
          <path d="M5.2 10.4L6.4 13.6" stroke={color} strokeWidth={sw} strokeLinecap="round" />
          <path d="M13.6 6.2C14.3 7.2 14.3 8.8 13.6 9.8" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case 'hr': // Trái tim / Con người Nhân sự
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <path
            d="M8 13.4C8 13.4 2.5 10 2.5 6.1C2.5 4.2 3.9 2.8 5.7 2.8C6.8 2.8 7.6 3.4 8 4.2C8.4 3.4 9.2 2.8 10.3 2.8C12.1 2.8 13.5 4.2 13.5 6.1C13.5 10 8 13.4 8 13.4Z"
            stroke={color}
            strokeWidth={sw}
            strokeLinejoin="round"
          />
        </svg>
      );
    case 'finance': // Đồng tiền / Ngân sách tài chính
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="6" stroke={color} strokeWidth={sw} />
          <path d="M8 4.2V11.8M10 5.9C9.6 5.2 8.9 5 8 5C6.8 5 6.1 5.6 6.1 6.4C6.1 7.3 6.9 7.7 8.1 8C9.3 8.3 10.1 8.7 10.1 9.6C10.1 10.5 9.3 11.1 8 11.1C7 11.1 6.2 10.8 5.8 10.1" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case 'education': // Mũ cử nhân / Học thuật
      return (
        <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
          <path d="M8 3L14.2 6.2L8 9.4L1.8 6.2L8 3Z" stroke={color} strokeWidth={sw} strokeLinejoin="round" />
          <path d="M4.2 7.8V11.2C4.2 12.1 5.9 13 8 13C10.1 13 11.8 12.1 11.8 11.2V7.8" stroke={color} strokeWidth={sw} strokeLinecap="round" />
          <path d="M13.6 6.8V10.6" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
  }
}

interface AgentRobotAvatarProps {
  agentId: AgentId;
  size?: number;
  mood?: OfficeChatMood;
  online?: boolean;
  /** Hiện huy hiệu Logo vai trò riêng ở góc dưới avatar (mặc định true) */
  showCrest?: boolean;
}

/**
 * Avatar Robot Eilik SVG mềm mại kết hợp Huy hiệu Logo Vai trò riêng cho từng Agent (11 màu × 11 logo):
 * - Đồng bộ 100% nhận diện màu sắc và mắt OLED với Robot 3D trong Văn phòng.
 * - Huy hiệu Logo vai trò giúp phân biệt tức thì RAG (Cyan + Kính lúp) vs Finance (Xanh lá rừng + Đồng tiền) và toàn bộ 11 Agent.
 */
export function AgentRobotAvatar({
  agentId,
  size = 34,
  mood = 'focus',
  online = false,
  showCrest = true,
}: AgentRobotAvatarProps) {
  const profile = AGENT_PROFILES[agentId];
  const accent = profile?.accentHex ?? '#d97706';
  const eyeColor =
    mood === 'happy'
      ? '#34d399'
      : mood === 'warn'
        ? '#fbbf24'
        : (AGENT_EYE_HEX[agentId] ?? '#38bdf8');
  const crestSize = Math.max(13, Math.round(size * 0.44));
  const glyphSize = Math.max(8, Math.round(crestSize * 0.66));

  return (
    <span
      className={`o3d-rava${online ? ' is-live' : ''}`}
      style={{ width: size, height: size, '--o3d-accent': accent } as CSSProperties}
      aria-hidden="true"
    >
      <svg viewBox="0 0 40 40" width={size} height={size} fill="none">
        {/* Nền sứ kem pha ánh màu nhẹ của từng Agent */}
        <circle cx="20" cy="20" r="19" fill={accent} fillOpacity="0.11" stroke={accent} strokeOpacity="0.34" strokeWidth="1.2" />

        {/* Vai & cổ áo đồng phục theo màu riêng */}
        <path d="M10.5 34.4C11.9 30.1 15.2 28.4 20 28.4C24.8 28.4 28.1 30.1 29.5 34.4" fill={accent} />
        <path d="M16.7 28.8L20 32.3L23.3 28.8" fill="#fffdf9" fillOpacity="0.92" />

        {/* Tai bo tròn theo màu riêng */}
        <rect x="6.5" y="15.4" width="3.8" height="8.4" rx="1.9" fill={accent} />
        <rect x="29.7" y="15.4" width="3.8" height="8.4" rx="1.9" fill={accent} />

        {/* Đầu sứ trắng kem bo tròn mềm */}
        <rect x="9.2" y="8.4" width="21.6" height="19.4" rx="9.2" fill="#fffdf9" stroke="#e4ddd2" strokeWidth="1" />

        {/* Chỏm đỉnh màu nhận diện */}
        <path d="M14.2 9.3C15.9 8.1 24.1 8.1 25.8 9.3C24.7 11 15.3 11 14.2 9.3Z" fill={accent} />

        {/* Mặt kính OLED đen sâu */}
        <rect x="11.6" y="12.5" width="16.8" height="12.2" rx="5.8" fill="#121721" />
        <ellipse cx="16.8" cy="14.5" rx="3.4" ry="1.05" fill="#ffffff" fillOpacity="0.13" />

        {/* Biểu cảm mắt LED mang đúng màu riêng của Agent */}
        {mood === 'happy' ? (
          <>
            <path d="M14.6 19.1C15.3 17.4 17.4 17.4 18.1 19.1" stroke={eyeColor} strokeWidth="1.9" strokeLinecap="round" />
            <path d="M21.9 19.1C22.6 17.4 24.7 17.4 25.4 19.1" stroke={eyeColor} strokeWidth="1.9" strokeLinecap="round" />
            <path d="M18.3 21.6C19.2 22.5 20.8 22.5 21.7 21.6" stroke={eyeColor} strokeWidth="1.4" strokeLinecap="round" />
          </>
        ) : mood === 'warn' ? (
          <>
            <circle cx="16.3" cy="18.5" r="1.8" fill={eyeColor} />
            <circle cx="23.7" cy="18.5" r="1.8" fill={eyeColor} />
            <path d="M18.4 22.1H21.6" stroke={eyeColor} strokeWidth="1.5" strokeLinecap="round" />
          </>
        ) : (
          <>
            <rect x="14.6" y="16.6" width="3.4" height="4.2" rx="1.7" fill={eyeColor} />
            <rect x="22.0" y="16.6" width="3.4" height="4.2" rx="1.7" fill={eyeColor} />
            <circle cx="15.8" cy="17.7" r="0.65" fill="#ffffff" fillOpacity="0.88" />
            <circle cx="23.2" cy="17.7" r="0.65" fill="#ffffff" fillOpacity="0.88" />
          </>
        )}
      </svg>

      {showCrest && (
        <span
          className="o3d-rava-crest"
          style={{
            width: crestSize,
            height: crestSize,
            background: accent,
          }}
        >
          <AgentRoleLogo agentId={agentId} size={glyphSize} color="#fffdf9" />
        </span>
      )}
      {online && <i className="o3d-rava-live-ring" />}
    </span>
  );
}
