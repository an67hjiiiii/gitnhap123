import React from 'react';
interface BrandLogoProps { size?: 'sm' | 'md' | 'lg'; showSubtitle?: boolean; theme?: 'light' | 'dark'; }
export const BrandLogo: React.FC<BrandLogoProps> = ({ size = 'md', showSubtitle = true, theme = 'light' }) => (
  <div className={`brand-lockup brand-${size} ${theme === 'dark' ? 'brand-inverse' : ''}`}>
    <svg width="35" height="35" viewBox="0 0 36 36" fill="none" aria-hidden="true"><rect x="1" y="1" width="34" height="34" rx="10" fill="currentColor"/><path d="M10 12h16v12H10z" stroke="var(--brand-mark-ink, #fff)" strokeWidth="1.5" strokeLinejoin="round"/><path d="M15 16v4m6-4v4M18 8v4" stroke="var(--brand-mark-ink, #fff)" strokeWidth="2" strokeLinecap="round"/></svg>
    <span><strong>OrchestrIQ<span className="brand-studio"> Studio</span></strong>{showSubtitle && <small>Nền tảng Multi-Agent RAG</small>}</span>
  </div>
);
