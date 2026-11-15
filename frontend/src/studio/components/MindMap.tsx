// Sơ đồ tư duy: cây cân hai bên quanh chủ đề trung tâm, mỗi nhánh một màu, thu/mở từng nhánh, kéo để di chuyển,
// Ctrl + cuộn (hoặc chụm hai ngón trên bàn di chuột) để phóng to, liên kết chéo giữa các nhánh, xuất SVG/PNG.
// Kiểu vẽ ghi thẳng vào thuộc tính SVG để tệp xuất giống hệt màn hình.
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { BookOpen, ChevronsDownUp, ChevronsUpDown, Download, Image as ImageIcon, Maximize2, Minus, Plus, Scan } from 'lucide-react';
import { MindLink, MindNode } from '../services/api';
import { saveBlob } from './analysis/exporters';

const PALETTE = ['#0e7490', '#4f46e5', '#b45309', '#be123c', '#047857', '#7c3aed', '#0369a1', '#a16207'];
const FONT = '"Be Vietnam Pro", "Segoe UI", Arial, sans-serif';
const INK = '#1f2933';
const STYLE = [
  { fs: 17, fw: 700, max: 22, px: 20, py: 12 },
  { fs: 14, fw: 600, max: 24, px: 14, py: 8 },
  { fs: 13, fw: 400, max: 30, px: 10, py: 6 },
];

interface Box { node: MindNode; depth: number; side: 1 | -1; color: string; lines: string[]; lh: number; fs: number; fw: number; w: number; h: number; x: number; y: number; parent?: Box; size: number; hidden: number }

let ctx: CanvasRenderingContext2D | null = null;
const textWidth = (s: string, fs: number, fw: number) => {
  ctx ??= document.createElement('canvas').getContext('2d');
  if (!ctx) return s.length * fs * 0.56;
  ctx.font = `${fw} ${fs}px ${FONT}`;
  return ctx.measureText(s).width;
};
function wrap(label: string, max: number): string[] {
  const lines: string[] = [];
  let cur = '';
  for (const w of label.split(/\s+/)) {
    if (cur && `${cur} ${w}`.length > max) { lines.push(cur); cur = w; } else cur = cur ? `${cur} ${w}` : w;
  }
  if (cur) lines.push(cur);
  return lines.length > 3 ? [...lines.slice(0, 2), `${lines[2]}…`] : lines;
}
const count = (n: MindNode): number => n.children.reduce((a, c) => a + 1 + count(c), 0);
const walk = (n: MindNode, depth = 0, out: [MindNode, number][] = []) => { out.push([n, depth]); n.children.forEach(c => walk(c, depth + 1, out)); return out; };

function layout(root: MindNode, collapsed: Set<string>) {
  const boxes = new Map<string, Box>();
  const build = (n: MindNode, depth: number, color: string, parent?: Box): Box => {
    const st = STYLE[Math.min(depth, 2)];
    const lines = wrap(n.label, st.max);
    const lh = Math.round(st.fs * 1.35);
    const b: Box = { node: n, depth, side: 1, color, lines, lh, fs: st.fs, fw: st.fw, parent, x: 0, y: 0, size: 0,
      w: Math.ceil(Math.max(...lines.map(l => textWidth(l, st.fs, st.fw)))) + st.px * 2, h: lines.length * lh + st.py * 2,
      hidden: collapsed.has(n.id) ? count(n) : 0 };
    boxes.set(n.id, b);
    const kids = collapsed.has(n.id) ? [] : n.children.map((c, i) => build(c, depth + 1, depth === 0 ? PALETTE[i % PALETTE.length] : color, b));
    const gap = depth === 0 ? 22 : depth === 1 ? 12 : 8;
    b.size = Math.max(b.h, kids.reduce((a, k) => a + k.size, 0) + gap * Math.max(0, kids.length - 1));
    return b;
  };
  const top = build(root, 0, '#17324a');
  const kidsOf = (b: Box) => (collapsed.has(b.node.id) ? [] : b.node.children).map(c => boxes.get(c.id)!);
  const place = (b: Box, edge: number, cy: number, side: 1 | -1) => {
    b.side = side; b.x = side === 1 ? edge : edge - b.w; b.y = cy;
    const kids = kidsOf(b);
    const gap = b.depth === 1 ? 12 : 8;
    let y = cy - (kids.reduce((a, k) => a + k.size, 0) + gap * Math.max(0, kids.length - 1)) / 2;
    const far = side === 1 ? b.x + b.w : b.x;
    for (const k of kids) { place(k, far + side * 48, y + k.size / 2, side); y += k.size + gap; } // chừa chỗ cho nút thu/mở
  };
  top.x = -top.w / 2; top.y = 0;
  const branches = kidsOf(top);
  const total = branches.reduce((a, k) => a + k.size, 0);
  const right: Box[] = [], left: Box[] = [];
  let acc = 0;
  for (const b of branches) { (branches.length < 3 || acc < total / 2 ? right : left).push(b); if (right.includes(b)) acc += b.size; }
  const stack = (group: Box[], side: 1 | -1) => {
    let y = -(group.reduce((a, k) => a + k.size, 0) + 22 * Math.max(0, group.length - 1)) / 2;
    for (const b of group) { place(b, side * (top.w / 2 + 56), y + b.size / 2, side); y += b.size + 22; }
  };
  stack(right, 1); stack(left.reverse(), -1); // bên trái xếp từ dưới lên để đọc theo chiều kim đồng hồ
  const all = [...boxes.values()];
  const bounds = { x: Math.min(...all.map(b => b.x)) - 40, y: Math.min(...all.map(b => b.y - b.h / 2)) - 40, r: Math.max(...all.map(b => b.x + b.w)) + 40, b: Math.max(...all.map(b => b.y + b.h / 2)) + 40 };
  return { boxes, all, bounds: { x: bounds.x, y: bounds.y, w: bounds.r - bounds.x, h: bounds.b - bounds.y } };
}

function edgePoint(b: Box, tx: number, ty: number) {
  const cx = b.x + b.w / 2, dx = tx - cx, dy = ty - b.y;
  const s = Math.min(Math.abs(dx) > 0.01 ? (b.w / 2) / Math.abs(dx) : Infinity, Math.abs(dy) > 0.01 ? (b.h / 2) / Math.abs(dy) : Infinity);
  return { x: cx + dx * s, y: b.y + dy * s };
}

export function MindMapCanvas({ root, links, fileName, onShowChunk }: { root: MindNode; links: MindLink[]; fileName: string; onShowChunk?: (chunkId: string) => void }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [size, setSize] = useState({ w: 800, h: 560 });
  const [full, setFull] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const nodes = useMemo(() => walk(root), [root]);
  const { boxes, all, bounds } = useMemo(() => layout(root, collapsed), [root, collapsed]);

  // Sơ đồ lớn: thu các nhánh cấp 2 lúc đầu cho dễ đọc.
  useEffect(() => {
    setSelected(null);
    setCollapsed(new Set(nodes.length > 45 ? nodes.filter(([n, d]) => d === 2 && n.children.length).map(([n]) => n.id) : []));
  }, [nodes]);
  useLayoutEffect(() => {
    const el = wrapRef.current; if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const fit = useCallback(() => {
    const k = Math.min(size.w / bounds.w, size.h / bounds.h, 1.25);
    setView({ k, x: size.w / 2 - (bounds.x + bounds.w / 2) * k, y: size.h / 2 - (bounds.y + bounds.h / 2) * k });
  }, [bounds, size]);
  useEffect(() => { fit(); }, [root, size.w, size.h, full]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onFs = () => setFull(document.fullscreenElement === wrapRef.current?.parentElement);
    document.addEventListener('fullscreenchange', onFs);
    return () => document.removeEventListener('fullscreenchange', onFs);
  }, []);
  useEffect(() => {
    const svg = svgRef.current; if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        const r = svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
        setView(v => { const k = Math.min(3, Math.max(0.2, v.k * Math.exp(-e.deltaY * 0.0025))); return { k, x: mx - (mx - v.x) * (k / v.k), y: my - (my - v.y) * (k / v.k) }; });
      } else setView(v => ({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY }));
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, []);

  const zoom = (f: number) => setView(v => { const k = Math.min(3, Math.max(0.2, v.k * f)); return { k, x: size.w / 2 - (size.w / 2 - v.x) * (k / v.k), y: size.h / 2 - (size.h / 2 - v.y) * (k / v.k) }; });
  const toggle = (id: string) => setCollapsed(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const expandAll = () => setCollapsed(new Set());
  const collapseAll = () => setCollapsed(new Set(nodes.filter(([n, d]) => d === 1 && n.children.length).map(([n]) => n.id)));
  const fullscreen = () => { const el = wrapRef.current?.parentElement; if (!el) return; document.fullscreenElement ? void document.exitFullscreen() : void el.requestFullscreen?.(); };

  const exportImage = (png: boolean) => {
    const svg = svgRef.current; if (!svg) return;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.querySelectorAll('[data-ui]').forEach(n => n.remove());
    clone.querySelector('[data-viewport]')?.removeAttribute('transform');
    clone.removeAttribute('style'); clone.removeAttribute('class');
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('viewBox', `${bounds.x} ${bounds.y} ${bounds.w} ${bounds.h}`);
    clone.setAttribute('width', String(Math.round(bounds.w))); clone.setAttribute('height', String(Math.round(bounds.h)));
    const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    Object.entries({ x: bounds.x, y: bounds.y, width: bounds.w, height: bounds.h, fill: '#ffffff' }).forEach(([k, v]) => bg.setAttribute(k, String(v)));
    clone.insertBefore(bg, clone.firstChild);
    const xml = new XMLSerializer().serializeToString(clone);
    if (!png) { saveBlob(`${fileName}.svg`, new Blob([xml], { type: 'image/svg+xml' })); return; }
    const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml;charset=utf-8' }));
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(2, 8000 / Math.max(bounds.w, bounds.h));
      const c = Object.assign(document.createElement('canvas'), { width: Math.round(bounds.w * scale), height: Math.round(bounds.h * scale) });
      const g = c.getContext('2d')!; g.scale(scale, scale); g.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      c.toBlob(b => b && saveBlob(`${fileName}.png`, b), 'image/png');
    };
    img.src = url;
  };

  const sel = selected ? boxes.get(selected) : undefined;
  const path = (b?: Box): Box[] => (b ? [...path(b.parent), b] : []);
  const far = (b: Box, side: 1 | -1) => (b.depth === 0 ? (side === 1 ? b.x + b.w : b.x) : b.side === 1 ? b.x + b.w : b.x);

  return (
    <div className={`mm${full ? ' is-full' : ''}`}>
      <div className="mm-bar" role="toolbar" aria-label="Điều khiển sơ đồ">
        <button type="button" onClick={() => zoom(1.2)} aria-label="Phóng to"><Plus size={15} /></button>
        <button type="button" onClick={() => zoom(1 / 1.2)} aria-label="Thu nhỏ"><Minus size={15} /></button>
        <button type="button" onClick={fit} title="Vừa khung"><Scan size={15} /><span>Vừa khung</span></button>
        <i />
        <button type="button" onClick={expandAll} title="Mở mọi nhánh"><ChevronsUpDown size={15} /><span>Mở hết</span></button>
        <button type="button" onClick={collapseAll} title="Chỉ hiện nhánh chính"><ChevronsDownUp size={15} /><span>Thu gọn</span></button>
        <i />
        <button type="button" onClick={() => exportImage(true)} title="Tải ảnh PNG"><ImageIcon size={15} /><span>PNG</span></button>
        <button type="button" onClick={() => exportImage(false)} title="Tải SVG (phóng to không vỡ nét)"><Download size={15} /><span>SVG</span></button>
        <button type="button" onClick={fullscreen} aria-label={full ? 'Thoát toàn màn hình' : 'Toàn màn hình'}><Maximize2 size={15} /></button>
        <span className="mm-zoom">{Math.round(view.k * 100)}%</span>
      </div>
      <div className="mm-stage" ref={wrapRef}>
        <svg ref={svgRef} width={size.w} height={size.h} role="tree" aria-label={`Sơ đồ tư duy: ${root.label}`}
          onPointerDown={e => { if ((e.target as Element).closest('[data-node]')) return; drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; (e.currentTarget as Element).setPointerCapture(e.pointerId); }}
          onPointerMove={e => { const d = drag.current; if (d) setView(v => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y })); }}
          onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
          onClick={e => { if (!(e.target as Element).closest('[data-node]')) setSelected(null); }}>
          <defs>
            <marker id="mm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#64748b" /></marker>
          </defs>
          <g data-viewport transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
            {all.filter(b => b.parent).map(b => {
              const p = b.parent!, sx = far(p, b.side), sy = p.y, ex = b.side === 1 ? b.x : b.x + b.w, ey = b.y, dx = Math.abs(ex - sx) * 0.55;
              return <path key={`l-${b.node.id}`} d={`M${sx} ${sy}C${sx + b.side * dx} ${sy} ${ex - b.side * dx} ${ey} ${ex} ${ey}`} fill="none"
                stroke={b.color} strokeWidth={b.depth === 1 ? 3 : b.depth === 2 ? 2 : 1.5} strokeOpacity={0.7} strokeLinecap="round" />;
            })}
            {links.map(l => {
              const a = boxes.get(l.from), b = boxes.get(l.to);
              if (!a || !b) return null;
              const ax = a.x + a.w / 2, bx = b.x + b.w / 2, mx = (ax + bx) / 2, my = (a.y + b.y) / 2, len = Math.hypot(bx - ax, b.y - a.y) || 1;
              const cx = mx - ((b.y - a.y) / len) * 50, cy = my + ((bx - ax) / len) * 50;
              const p1 = edgePoint(a, cx, cy), p2 = edgePoint(b, cx, cy);
              const lx = 0.25 * p1.x + 0.5 * cx + 0.25 * p2.x, ly = 0.25 * p1.y + 0.5 * cy + 0.25 * p2.y;
              return <g key={`x-${l.from}-${l.to}`}>
                <path d={`M${p1.x} ${p1.y}Q${cx} ${cy} ${p2.x} ${p2.y}`} fill="none" stroke="#64748b" strokeWidth={1.5} strokeDasharray="5 4" markerEnd="url(#mm-arrow)" />
                {l.label && <text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle" fontFamily={FONT} fontSize={11.5} fontStyle="italic" fill="#475569" stroke="#ffffff" strokeWidth={4} paintOrder="stroke">{l.label}</text>}
              </g>;
            })}
            {all.map(b => {
              const isSel = selected === b.node.id, root0 = b.depth === 0, has = b.node.children.length > 0;
              const fill = root0 ? '#17324a' : b.depth === 1 ? `${b.color}1a` : '#ffffff';
              const tx = b.x + b.w / 2, ty = b.y - (b.lines.length * b.lh) / 2 + b.lh / 2;
              return <g key={b.node.id} data-node={b.node.id} tabIndex={0} role="treeitem" aria-selected={isSel} aria-expanded={has ? !collapsed.has(b.node.id) : undefined}
                aria-label={b.node.label} className="mm-node"
                onClick={() => setSelected(b.node.id)}
                onDoubleClick={() => has && !root0 && toggle(b.node.id)}
                onKeyDown={e => { if (e.key === 'Enter') setSelected(b.node.id); if (e.key === ' ' && has && !root0) { e.preventDefault(); toggle(b.node.id); } }}>
                {isSel && <rect data-ui x={b.x - 4} y={b.y - b.h / 2 - 4} width={b.w + 8} height={b.h + 8} rx={root0 ? (b.h + 8) / 2 : 12} fill="none" stroke={root0 ? '#0e7490' : b.color} strokeOpacity={0.35} strokeWidth={5} />}
                <rect className="mm-box" x={b.x} y={b.y - b.h / 2} width={b.w} height={b.h} rx={root0 ? Math.min(b.h / 2, 22) : b.depth === 1 ? 10 : 8}
                  fill={fill} stroke={root0 ? '#17324a' : b.color} strokeOpacity={b.depth >= 2 ? 0.45 : 1} strokeWidth={b.depth === 1 ? 1.5 : 1} />
                <text x={tx} textAnchor="middle" fontFamily={FONT} fontSize={b.fs} fontWeight={b.fw} fill={root0 ? '#ffffff' : INK}>
                  {b.lines.map((l, i) => <tspan key={i} x={tx} y={ty + i * b.lh} dominantBaseline="middle">{l}</tspan>)}
                </text>
                <title>{b.node.label}</title>
                {has && !root0 && <g data-ui className="mm-toggle" onClick={e => { e.stopPropagation(); toggle(b.node.id); }}>
                  <circle cx={far(b, b.side) + b.side * 12} cy={b.y} r={b.hidden ? 10 : 8} fill="#ffffff" stroke={b.color} strokeWidth={1.5} />
                  <text x={far(b, b.side) + b.side * 12} y={b.y} textAnchor="middle" dominantBaseline="central" fontFamily={FONT} fontSize={b.hidden ? 10 : 13} fontWeight={700} fill={b.color}>{b.hidden ? (b.hidden > 99 ? '99+' : b.hidden) : '−'}</text>
                </g>}
              </g>;
            })}
          </g>
        </svg>
        <p className="mm-hint">Kéo để di chuyển · Ctrl + cuộn để phóng to · bấm nút tròn để thu/mở nhánh</p>
      </div>
      {sel && <div className="mm-detail" aria-live="polite">
        <nav aria-label="Vị trí trong sơ đồ">{path(sel).map((b, i) => <span key={b.node.id}>{i > 0 && ' › '}{b.node.label}</span>)}</nav>
        <div>
          {sel.node.children.length > 0 && sel.depth > 0 && <button type="button" className="btn btn-ghost is-sm" onClick={() => toggle(sel.node.id)}>{collapsed.has(sel.node.id) ? `Mở ${count(sel.node)} ý` : 'Thu nhánh'}</button>}
          {sel.node.chunk_id && onShowChunk && <button type="button" className="btn btn-dark is-sm" onClick={() => onShowChunk(sel.node.chunk_id!)}><BookOpen size={14} />Xem đoạn nguồn</button>}
        </div>
      </div>}
    </div>
  );
}
