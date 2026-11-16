import React from 'react';
import './brand-logo.css';
interface BrandLogoProps { size?: 'sm' | 'md' | 'lg'; showSubtitle?: boolean; theme?: 'light' | 'dark'; }
export const BrandLogo: React.FC<BrandLogoProps> = ({ size = 'md', showSubtitle = true, theme = 'light' }) => (
  <div className={`brand-lockup brand-${size} ${theme === 'dark' ? 'brand-inverse' : ''}`}>
    <img className="oq-brand-emblem" src="/orchestriq-mark.svg" width="48" height="48" alt="" aria-hidden="true" draggable={false}/>
    <span><strong>OrchestrIQ<span className="brand-studio"> Studio</span></strong>{showSubtitle && <small>Nền tảng Multi-Agent RAG</small>}</span>
  </div>
);
