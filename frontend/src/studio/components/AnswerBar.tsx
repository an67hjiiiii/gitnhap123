import React from 'react';
import { Clock, Coins, FileText } from 'lucide-react';

// Hàng nút dưới câu trả lời, dùng chung cho Hỏi nhanh, Phân tích và Trả lời trực tiếp:
// số đo rút gọn (icon + số, rê chuột để xem đầy đủ) rồi các nút chỉ có icon, luôn một hàng.
export type BarAction = {
  key: string; label: string; icon: React.ReactNode; onClick: () => void;
  show?: boolean; pressed?: boolean; expanded?: boolean;
};

export function AnswerBar({ secs, tokens, tokensTitle, sources, actions, children }: {
  secs?: number; tokens?: number; tokensTitle?: string; sources?: number; actions: BarAction[]; children?: React.ReactNode;
}) {
  const vi = (n: number, d = 1) => n.toLocaleString('vi-VN', { maximumFractionDigits: d });
  const shortTokens = (n: number) => n >= 1000 ? `${vi(n / 1000)}k` : String(n);
  const hasMeta = (secs != null && secs > 0) || !!tokens || !!sources;
  return (
    <footer className="ws-bar">
      {hasMeta && <span className="ws-meta">
        {secs != null && secs > 0 && <span title={`${vi(secs)} giây xử lý`}><Clock size={13} />{vi(secs)} s</span>}
        {!!tokens && <span title={tokensTitle ?? `${tokens.toLocaleString('vi-VN')} token`}><Coins size={13} />{shortTokens(tokens)}</span>}
        {!!sources && <span title={`${sources} nguồn`}><FileText size={13} />{sources}</span>}
      </span>}
      <span className="ws-acts">
        {actions.filter(a => a.show !== false).map(a => (
          <button key={a.key} type="button" title={a.label} aria-label={a.label}
            aria-pressed={a.pressed} aria-expanded={a.expanded} onClick={a.onClick}>{a.icon}</button>
        ))}
        {children}
      </span>
    </footer>
  );
}
