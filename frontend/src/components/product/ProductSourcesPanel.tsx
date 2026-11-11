import { useEffect, useState } from "react";
import { ArrowLeftIcon, FileTextIcon, XIcon } from "@phosphor-icons/react";
import { ownerScopedRetrieval } from "../../lib/api";
import type { RunRecord, SourceChunk, SourceDetail } from "../../types/api";
import "./product-sources-panel.css";

interface ProductSourcesPanelProps {
  run: RunRecord;
  onClose: () => void;
}

interface SourceEntry {
  sourceId: string;
  sourceName: string;
  chunks: SourceChunk[];
}

function unique(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

function citationIds(run: RunRecord) {
  return unique([
    ...(run.events ?? []).flatMap((event) => event.result?.citations ?? []),
    ...(run.task_results ?? []).flatMap((result) => result.citations ?? []),
  ]);
}

function isVerifiedChunk(chunk: SourceChunk, requestedId: string): boolean {
  return chunk.chunk_id === requestedId
    && Boolean(chunk.source_id?.trim())
    && Boolean(chunk.source_name?.trim())
    && typeof chunk.text === "string"
    && Boolean(chunk.text.trim());
}

function excerpt(text: string): string {
  const clean = text.trim().replace(/\s+/g, " ");
  return clean.length > 320 ? `${clean.slice(0, 317).trimEnd()}…` : clean;
}

export function ProductSourcesPanel({ run, onClose }: ProductSourcesPanelProps) {
  const [entries, setEntries] = useState<SourceEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [unavailableCount, setUnavailableCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [openedDocument, setOpenedDocument] = useState<SourceDetail | null>(null);
  const [openingSourceId, setOpeningSourceId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const ids = citationIds(run);
    setIsLoading(true);
    setEntries([]);
    setUnavailableCount(0);
    setError(null);
    setOpenedDocument(null);

    void Promise.allSettled(ids.map((id) => ownerScopedRetrieval.getChunk(id))).then((results) => {
      if (cancelled) return;
      const chunks = results.flatMap((result, index) =>
        result.status === "fulfilled" && isVerifiedChunk(result.value, ids[index]) ? [result.value] : [],
      );
      const bySource = new Map<string, SourceEntry>();
      for (const chunk of chunks) {
        const entry = bySource.get(chunk.source_id) ?? {
          sourceId: chunk.source_id,
          sourceName: chunk.source_name,
          chunks: [],
        };
        entry.chunks.push(chunk);
        bySource.set(chunk.source_id, entry);
      }
      setEntries([...bySource.values()]);
      setUnavailableCount(ids.length - chunks.length);
      setIsLoading(false);
    });

    return () => { cancelled = true; };
  }, [run.run_id]);

  async function openDocument(entry: SourceEntry) {
    setOpeningSourceId(entry.sourceId);
    setError(null);
    try {
      const source = await ownerScopedRetrieval.getSource(entry.sourceId);
      const validChunks = (source.chunks ?? []).filter((chunk) =>
        chunk.source_id === entry.sourceId && typeof chunk.text === "string" && Boolean(chunk.text.trim()),
      );
      const hasCitedChunk = validChunks.some((chunk) => entry.chunks.some((citation) => citation.chunk_id === chunk.chunk_id));
      if (source.source_id !== entry.sourceId || !source.source_name?.trim() || !hasCitedChunk || validChunks.length === 0) {
        throw new Error("Source is unavailable");
      }
      setOpenedDocument({ ...source, chunks: validChunks });
    } catch {
      setOpenedDocument(null);
      setError("Không thể mở tài liệu này. Nguồn có thể không còn khả dụng trong không gian hiện tại.");
    } finally {
      setOpeningSourceId(null);
    }
  }

  return (
    <aside className="product-sources-panel" aria-label="Nguồn tham khảo">
      <header className="product-sources-panel-header">
        {openedDocument ? (
          <button className="product-sources-back" type="button" onClick={() => setOpenedDocument(null)} aria-label="Quay lại nguồn tham khảo" title="Quay lại nguồn tham khảo">
            <ArrowLeftIcon size={18} aria-hidden="true" />
          </button>
        ) : <span className="product-sources-header-icon" aria-hidden="true"><FileTextIcon size={18} /></span>}
        <h2>{openedDocument ? openedDocument.source_name : "Nguồn tham khảo"}</h2>
        <button className="product-sources-close" type="button" onClick={onClose} aria-label="Đóng nguồn tham khảo" title="Đóng">
          <XIcon size={18} aria-hidden="true" />
        </button>
      </header>
      <div className="product-sources-panel-body" aria-busy={isLoading || openingSourceId !== null}>
        {openedDocument ? (
          <article className="product-source-document" aria-label={`Nội dung ${openedDocument.source_name}`}>
            {openedDocument.chunks.map((chunk, index) => (
              <section key={chunk.chunk_id} className="product-source-document-chunk">
                {openedDocument.chunks.length > 1 && <h3>Đoạn {index + 1}</h3>}
                <p>{chunk.text}</p>
              </section>
            ))}
          </article>
        ) : isLoading ? (
          <p className="product-sources-state" role="status">Đang tải nguồn tham khảo…</p>
        ) : entries.length === 0 ? (
          <div className="product-sources-empty"><h3>Chưa thể hiển thị nguồn</h3><p>Nguồn dẫn không còn truy cập được trong không gian hiện tại.</p></div>
        ) : (
          <>
            {unavailableCount > 0 && <p className="product-sources-notice" role="status">Một số nguồn dẫn không còn truy cập được và đã được ẩn.</p>}
            {error && <p className="product-sources-error" role="alert">{error}</p>}
            <ul className="product-sources-list">
              {entries.map((entry) => (
                <li className="product-source-entry" key={entry.sourceId}>
                  <div className="product-source-entry-heading"><FileTextIcon size={17} aria-hidden="true" /><h3 title={entry.sourceName}>{entry.sourceName}</h3></div>
                  <div className="product-source-excerpts">
                    {entry.chunks.map((chunk) => <blockquote key={chunk.chunk_id}>{excerpt(chunk.text)}</blockquote>)}
                  </div>
                  <button className="product-source-open" type="button" onClick={() => void openDocument(entry)} disabled={openingSourceId !== null}>
                    {openingSourceId === entry.sourceId ? "Đang mở…" : "Mở tài liệu"}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
        {error && openedDocument && <p className="product-sources-error" role="alert">{error}</p>}
      </div>
    </aside>
  );
}
