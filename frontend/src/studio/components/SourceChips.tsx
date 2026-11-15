import React, { useEffect, useMemo, useState } from 'react';
import { FileText } from 'lucide-react';
import { getChunk } from '../services/api';
import { Cap1Run } from '../services/adapt';

// Nguồn của một câu trả lời, gộp theo tài liệu. Mã chunk không bao giờ hiện ra ngoài; trong khung đoạn trích chỉ có "đoạn N".
export interface SourceItem { n: number; doc_name: string; section?: string; snippet?: string; chunk_no?: number }

const MAX_CHIPS = 3;
// Rút gọn giữa tên tệp, giữ phần đuôi: "bao_cao_tai_chinh_2026.pdf" -> "bao_cao_t…2026.pdf".
export function shortName(name: string, max = 26): string {
  if (name.length <= max) return name;
  const keep = max - 1, tail = Math.min(10, Math.floor(keep / 2));
  return `${name.slice(0, keep - tail)}…${name.slice(name.length - tail)}`;
}
const chunkNo = (id: string) => { const m = /_c(\d+)$/.exec(id); return m ? Number(m[1]) + 1 : undefined; };

function useSources(run?: Cap1Run): SourceItem[] {
  const given: SourceItem[] | null = Array.isArray(run?.sources) && run!.sources.length ? run!.sources : null;
  const ids: string[] = useMemo(() => [...new Set<string>((run?.task_results || []).flatMap((r: any) => r.citations || []))], [run]);
  const [fetched, setFetched] = useState<SourceItem[]>([]);
  useEffect(() => {
    // Lượt trả lời cũ chưa lưu `sources`: lấy tên tệp từ từng đoạn được trích.
    if (given || !ids.length) { setFetched([]); return; }
    let live = true;
    Promise.all(ids.map((id, i) => getChunk(id).then(c => ({ n: i + 1, doc_name: c.source_name || 'Tài liệu', snippet: c.text, chunk_no: chunkNo(id) } as SourceItem)).catch(() => null)))
      .then(list => { if (live) setFetched(list.filter(Boolean) as SourceItem[]); });
    return () => { live = false; };
  }, [given, ids]);
  return given ?? fetched;
}

export const SourceChips: React.FC<{ run?: Cap1Run }> = ({ run }) => {
  const sources = useSources(run);
  const [open, setOpen] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const groups = useMemo(() => {
    const map = new Map<string, SourceItem[]>();
    sources.forEach(s => map.set(s.doc_name, [...(map.get(s.doc_name) ?? []), s]));
    return [...map.entries()].map(([doc, items]) => ({ doc, items }));
  }, [sources]);
  if (!groups.length) return null;
  const shown = all ? groups : groups.slice(0, MAX_CHIPS);
  const hidden = groups.length - shown.length;
  const current = groups.find(g => g.doc === open);
  return (
    <div className="cht-src">
      <div className="cht-src-row">
        {shown.map(g => (
          <button key={g.doc} type="button" className={`cht-chip${open === g.doc ? ' is-on' : ''}`} aria-expanded={open === g.doc}
            title={g.doc} onClick={() => setOpen(open === g.doc ? null : g.doc)}>
            <FileText size={12} />
            <span className="cht-chip-n">{g.items.map(i => `[${i.n}]`).join('')}</span>
            <span>{shortName(g.doc)}</span>
            <small>· {g.items.length} đoạn</small>
          </button>
        ))}
        {hidden > 0 && <button type="button" className="cht-chip is-more" onClick={() => setAll(true)}>+{hidden} nguồn</button>}
      </div>
      {current && <div className="cht-src-pop" role="region" aria-label={`Đoạn trích từ ${current.doc}`}>
        {current.items.map(i => (
          <section key={i.n}>
            <h5>[{i.n}] {i.chunk_no ? `đoạn ${i.chunk_no}` : 'đoạn trích'}{i.section ? ` · ${i.section}` : ''}</h5>
            <p>{i.snippet || 'Không có đoạn trích.'}</p>
          </section>
        ))}
      </div>}
    </div>
  );
};
