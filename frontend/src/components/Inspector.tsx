import { useState } from "react";
import { XIcon } from "@phosphor-icons/react";
import type { InspectorTab } from "../app/useResearchApp";
import type { RunRecord, SourceChunk, SourceDetail, SourceSummary } from "../types/api";
import { ownerScopedRetrieval } from "../lib/api";
import { getStatusTone, normalizeStatus, StatusBadge } from "./StatusBadge";

interface InspectorProps {
  researchMode: boolean;
  run: RunRecord | null;
  sources: SourceSummary[];
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
}
const tabs: Array<{ id: InspectorTab; label: string }> = [
  { id: "evidence", label: "Evidence" },
  { id: "sources", label: "Sources" },
  { id: "metrics", label: "Metrics" },
];

function productStatusLabel(status?: RunRecord["status"]): string {
  const labels: Record<string, string> = {
    READY: "Sẵn sàng",
    RUNNING: "Đang xử lý",
    COMPLETE: "Đã hoàn tất",
    PARTIAL: "Câu trả lời một phần",
    NO_EVIDENCE: "Chưa có nguồn phù hợp",
    FAILED: "Chưa thể hoàn thành",
  };
  return labels[normalizeStatus(status)] ?? "Đang cập nhật";
}

function ProductInspectorStatus({ status }: { status?: RunRecord["status"] }) {
  return <span className={`status-badge status-${getStatusTone(status)}`} role="status">{productStatusLabel(status)}</span>;
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return new Intl.NumberFormat().format(value);
  return String(value);
}

function unique(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

export function getEvidenceEvents(run: RunRecord | null) {
  return (run?.events ?? []).filter(
    (event) => Boolean(event.selected?.length || event.dropped?.length),
  );
}

export function getEvidenceIds(run: RunRecord | null) {
  return unique([
    ...(run?.events ?? []).flatMap((event) => event.selected ?? []),
    ...(run?.events ?? []).flatMap((event) => event.result?.evidence_ids ?? []),
    ...(run?.task_results ?? []).flatMap((result) => result.evidence_ids ?? []),
  ]);
}

export function getRunCitations(run: RunRecord | null) {
  return {
    valid: unique([
      ...(run?.events ?? []).flatMap((event) => event.result?.citations ?? []),
      ...(run?.task_results ?? []).flatMap((result) => result.citations ?? []),
    ]),
    invalid: unique([
      ...(run?.events ?? []).flatMap((event) => event.result?.invalid_citations ?? []),
      ...(run?.task_results ?? []).flatMap((result) => result.invalid_citations ?? []),
    ]),
  };
}

function ChunkPreview({ chunk, onClose, researchMode = true }: { chunk: SourceChunk; onClose: () => void; researchMode?: boolean }) {
  const score = chunk.score === undefined ? "" : ` · score ${chunk.score.toFixed(3)}`;
  return (
    <div className="chunk-preview" aria-live="polite">
      <div className="chunk-preview-heading">
        <span title={researchMode ? chunk.chunk_id : chunk.source_name}>{researchMode ? chunk.chunk_id : chunk.source_name}</span>
        <button type="button" className="close-preview" aria-label={researchMode ? "Close source preview" : "Đóng nguồn"} title={researchMode ? "Close source preview" : "Đóng nguồn"} onClick={onClose}>{researchMode ? "×" : <XIcon size={18} aria-hidden="true" />}</button>
      </div>
      <div className="source-card-meta">{researchMode ? `${chunk.source_name} · chunk ${chunk.index + 1}${score}` : `Đoạn ${chunk.index + 1}`}</div>
      <pre aria-label={researchMode ? `Text from ${chunk.chunk_id}` : `Nội dung từ ${chunk.source_name}, đoạn ${chunk.index + 1}`}>{chunk.text}</pre>
    </div>
  );
}

function InspectableIds({
  ids,
  loadingId,
  onInspect,
  emptyLabel = "None recorded",
  researchMode = true,
  productLabel = "Mở nguồn",
}: {
  ids: string[];
  loadingId: string | null;
  onInspect: (id: string) => void;
  emptyLabel?: string;
  researchMode?: boolean;
  productLabel?: string;
}) {
  if (ids.length === 0) return <span className="source-card-meta">{emptyLabel}</span>;
  return (
    <div>
      {ids.map((id) => (
        <button
          type="button"
          className="evidence-id text-button"
          key={id}
          disabled={loadingId !== null && loadingId !== id}
          aria-label={researchMode ? `Inspect evidence ${id}` : productLabel}
          onClick={() => onInspect(id)}
        >
          {loadingId === id ? (researchMode ? "Loading…" : "Đang mở…") : (researchMode ? id : productLabel)}
        </button>
      ))}
    </div>
  );
}

function EvidencePanel({ run, researchMode }: { run: RunRecord | null; researchMode: boolean }) {
  const [selectedChunk, setSelectedChunk] = useState<SourceChunk | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [chunkError, setChunkError] = useState<string | null>(null);
  const events = getEvidenceEvents(run);
  const results = run?.task_results ?? [];
  const citations = getRunCitations(run);

  async function inspectChunk(chunkId: string) {
    setLoadingId(chunkId);
    setChunkError(null);
    try {
      setSelectedChunk(await ownerScopedRetrieval.getChunk(chunkId));
    } catch (cause) {
      setSelectedChunk(null);
      setChunkError(researchMode ? (cause instanceof Error ? cause.message : "Unable to load this evidence") : "Không thể mở nguồn này. Hãy thử lại.");
    } finally {
      setLoadingId(null);
    }
  }

  if (!run) return <EmptyPanel title={researchMode ? "No run selected" : "Chưa có câu trả lời"} copy={researchMode ? "Evidence will appear after your first run." : "Nguồn sẽ xuất hiện cùng câu trả lời."} />;
  if (!researchMode) {
    return (
      <div className="inspector-list">
        <div className="evidence-card">
          <div className="evidence-card-heading"><span>Nguồn được dẫn</span></div>
          {citations.valid.length > 0
            ? <InspectableIds ids={citations.valid} loadingId={loadingId} onInspect={(id) => void inspectChunk(id)} researchMode={false} />
            : <p className="source-card-meta">Câu trả lời này không có nguồn được dẫn.</p>}
        </div>
        {chunkError && <div className="inspector-empty" role="alert"><strong>Không thể mở nguồn</strong><span>{chunkError}</span></div>}
        {selectedChunk && <ChunkPreview chunk={selectedChunk} onClose={() => setSelectedChunk(null)} researchMode={false} />}
      </div>
    );
  }
  if (events.length === 0 && results.length === 0) return <EmptyPanel title="No evidence trace" copy="This run did not return retrieval events." />;

  return (
    <div className="inspector-list">
      {events.length === 0 ? (
        <EmptyPanel title="No retrieval trace" copy="This run returned task results without retrieval events." />
      ) : (
        events.map((event, index) => {
          const selected = unique(event.selected ?? []);
          const dropped = unique((event.dropped ?? []).map((item) => item.chunk_id ?? ""));
          return (
            <div className="evidence-card" key={`${event.stage}-${event.task_id ?? index}`}>
              <div className="evidence-card-heading">
                <span>{event.task_id ?? "Run retrieval"}</span>
                <span className="evidence-stage">{event.stage}</span>
              </div>
              <div className="evidence-row"><span>Selected evidence</span><strong>{selected.length}</strong></div>
              <InspectableIds ids={selected} loadingId={loadingId} onInspect={(id) => void inspectChunk(id)} />
              <div className="evidence-row evidence-row-muted"><span>Dropped evidence</span><strong>{event.dropped?.length ?? 0}</strong></div>
              {dropped.length > 0 && <InspectableIds ids={dropped} loadingId={loadingId} onInspect={(id) => void inspectChunk(id)} emptyLabel="No chunk locator" />}
              {event.dropped?.map((item, droppedIndex) => (
                <div className="source-card-meta" key={`${item.chunk_id ?? "dropped"}-${droppedIndex}`}>
                  {item.reason ?? "Dropped by context budget"}{item.estimated_tokens === undefined ? "" : ` · ${item.estimated_tokens} tokens`}
                </div>
              ))}
            </div>
          );
        })
      )}

      {results.length > 0 && (
        <div className="evidence-card">
          <div className="evidence-card-heading"><span>Citation audit</span><span className="evidence-stage">{citations.valid.length} valid · {citations.invalid.length} invalid</span></div>
          {results.map((result, index) => {
            const evidenceIds = unique(result.evidence_ids ?? []);
            const valid = unique(result.citations ?? []);
            const invalid = unique(result.invalid_citations ?? []);
            return (
              <div className="source-card" key={`${result.task_id}-${index}`}>
                <div className="source-card-heading"><span className="source-name">{result.task_id}{result.domain ? ` · ${result.domain}` : ""}</span><StatusBadge compact status={result.status} /></div>
                <div className="evidence-row"><span>Evidence IDs</span><strong>{evidenceIds.length}</strong></div>
                <InspectableIds ids={evidenceIds} loadingId={loadingId} onInspect={(id) => void inspectChunk(id)} />
                <div className="evidence-row"><span>Valid citations</span><strong>{valid.length}</strong></div>
                <InspectableIds ids={valid} loadingId={loadingId} onInspect={(id) => void inspectChunk(id)} />
                {invalid.length > 0 && <><div className="evidence-row evidence-row-muted"><span>Invalid citations</span><strong>{invalid.length}</strong></div><div>{invalid.map((id) => <code className="evidence-id" key={id}>{id}</code>)}</div></>}
                {(result.missing_information ?? []).length > 0 && <div className="source-card-meta">Missing: {result.missing_information?.join("; ")}</div>}
              </div>
            );
          })}
        </div>
      )}

      {chunkError && <div className="inspector-empty" role="alert"><strong>Unable to inspect evidence</strong><span>{chunkError}</span></div>}
      {selectedChunk && <ChunkPreview chunk={selectedChunk} onClose={() => setSelectedChunk(null)} />}
    </div>
  );
}

function sourceStatus(source: SourceSummary | SourceDetail): string {
  const explicit = "status" in source ? source.status : undefined;
  const indexed = "index_status" in source ? source.index_status : undefined;
  const reported = explicit ?? indexed;
  if (reported?.trim()) return reported;
  const chunkCount = "chunks" in source ? source.chunks.length : source.chunk_count;
  return chunkCount > 0 ? "READY" : "EMPTY";
}

function SourcesPanel({ sources, researchMode }: { sources: SourceSummary[]; researchMode: boolean }) {
  const [selectedSource, setSelectedSource] = useState<SourceDetail | null>(null);
  const [selectedChunk, setSelectedChunk] = useState<SourceChunk | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);

  async function inspectSource(source: SourceSummary) {
    setLoadingId(source.source_id);
    setSourceError(null);
    setSelectedChunk(null);
    try {
      setSelectedSource(await ownerScopedRetrieval.getSource(source.source_id));
    } catch (cause) {
      setSelectedSource(null);
      setSourceError(researchMode ? (cause instanceof Error ? cause.message : "Unable to load this source") : "Không thể mở tài liệu này. Hãy thử lại.");
    } finally {
      setLoadingId(null);
    }
  }

  if (sources.length === 0) return <EmptyPanel title={researchMode ? "Corpus is empty" : "Chưa có tài liệu"} copy={researchMode ? "Add a UTF-8 text or code file to begin." : "Tài liệu đã tải lên sẽ xuất hiện ở đây."} />;

  return (
    <div className="inspector-list">
      {sources.map((source) => (
        <div className="source-card" key={source.source_id}>
          <div className="source-card-heading">
            <span className="source-file-icon" aria-hidden="true">TXT</span>
            <span className="source-name">{source.source_name}</span>
            <StatusBadge compact status={sourceStatus(source)} />
          </div>
          <div className="source-card-meta">
            {source.chunk_count} {researchMode ? (source.chunk_count === 1 ? "chunk" : "chunks") : (source.chunk_count === 1 ? "đoạn" : "đoạn trích")}{researchMode ? ` · ${source.source_id}` : ""}
          </div>
          <button className="text-button" type="button" onClick={() => void inspectSource(source)} disabled={loadingId !== null}>
            {loadingId === source.source_id
              ? (researchMode ? "Loading…" : "Đang mở…")
              : selectedSource?.source_id === source.source_id
                ? (researchMode ? "Refresh chunks" : "Làm mới đoạn trích")
                : (researchMode ? "Inspect chunks" : "Xem đoạn trích")}
          </button>
        </div>
      ))}

      {sourceError && (
        <div className="inspector-empty" role="alert">
          <strong>{researchMode ? "Unable to load source" : "Không thể mở tài liệu"}</strong>
          <span>{sourceError}</span>
        </div>
      )}

      {selectedSource && (
        <div className="source-card">
          <div className="source-card-heading">
            <span className="source-name" title={selectedSource.source_name}>{selectedSource.source_name}</span>
            <StatusBadge compact status={sourceStatus(selectedSource)} />
            <button
              type="button"
              className="close-preview"
              aria-label={researchMode ? "Close source details" : "Đóng tài liệu"}
              title={researchMode ? "Close source details" : "Đóng tài liệu"}
              onClick={() => {
                setSelectedSource(null);
                setSelectedChunk(null);
              }}
            >
              {researchMode ? "×" : <XIcon size={18} aria-hidden="true" />}
            </button>
          </div>
          <div className="source-card-meta">
            {selectedSource.chunks.length} {researchMode ? (selectedSource.chunks.length === 1 ? "chunk" : "chunks") : "đoạn trích"}{researchMode ? ` · ${selectedSource.source_id}` : ""}
          </div>
          {selectedSource.chunks.length === 0 ? (
            <span className="source-card-meta">{researchMode ? "This source has no stored chunks." : "Tài liệu chưa có đoạn văn bản được lưu."}</span>
          ) : (
            selectedSource.chunks.map((chunk) => (
              <div className="evidence-row" key={chunk.chunk_id}>
                <span>Chunk {chunk.index + 1}</span>
                <button
                  type="button"
                  className="text-button"
                  title={researchMode ? `Inspect ${chunk.chunk_id}` : `Mở đoạn ${chunk.index + 1}`}
                  onClick={() => setSelectedChunk(chunk)}
                >
                  {researchMode ? chunk.chunk_id : `Mở đoạn ${chunk.index + 1}`}
                </button>
              </div>
            ))
          )}
        </div>
      )}

      {selectedChunk && (
        <div className="chunk-preview">
          <div className="chunk-preview-heading">
            <span>{researchMode ? selectedChunk.chunk_id : selectedSource?.source_name ?? "Tài liệu"}</span>
            <button type="button" className="close-preview" aria-label={researchMode ? "Close source preview" : "Đóng nguồn"} title={researchMode ? "Close source preview" : "Đóng nguồn"} onClick={() => setSelectedChunk(null)}>{researchMode ? "×" : <XIcon size={18} aria-hidden="true" />}</button>
          </div>
          <pre aria-label={researchMode ? undefined : `Nội dung từ ${selectedSource?.source_name ?? "tài liệu"}, đoạn ${selectedChunk.index + 1}`}>{selectedChunk.text}</pre>
        </div>
      )}
    </div>
  );
}

function MetricsPanel({ run }: { run: RunRecord | null }) {
  const metrics = run?.metrics;
  const entries = metrics
    ? [
        ["Total latency", metrics.latency_ms === undefined ? undefined : `${formatValue(metrics.latency_ms)} ms`],
        ["LLM calls", metrics.llm_calls],
        ["Total tokens", metrics.total_tokens],
        ["Selected chunks", metrics.selected_chunks],
        ["Valid citations", metrics.citations_valid],
        ["Citation validity", metrics.citation_locator_validity === null || metrics.citation_locator_validity === undefined ? undefined : `${Math.round(metrics.citation_locator_validity * 100)}%`],
      ]
    : [];

  if (!run) return <EmptyPanel title="No metrics yet" copy="Runtime measurements will appear after a run." />;
  return (
    <div className="metric-list">
      {entries.map(([label, value]) => (
        <div className="metric-row" key={label}>
          <span>{label}</span>
          <strong>{formatValue(value)}</strong>
        </div>
      ))}
      <div className="run-metadata">
        <span>Snapshot</span><code>{run.source_snapshot_id ?? "—"}</code>
        <span>Config hash</span><code>{run.config_hash ?? "—"}</code>
      </div>
    </div>
  );
}

function EmptyPanel({ title, copy }: { title: string; copy: string }) {
  return <div className="inspector-empty"><strong>{title}</strong><span>{copy}</span></div>;
}

export function Inspector({ researchMode, run, sources, activeTab, onTabChange }: InspectorProps) {
  const productActiveTab: InspectorTab = activeTab === "sources" ? "sources" : "evidence";
  const selectedTab = researchMode ? activeTab : productActiveTab;
  const visibleTabs: Array<{ id: InspectorTab; label: string }> = researchMode
    ? tabs
    : [{ id: "evidence", label: "Nguồn được dẫn" }, { id: "sources", label: "Tài liệu" }];
  return (
    <aside className={`inspector${researchMode ? "" : " product-inspector"}`} aria-label={researchMode ? "Run inspector" : "Nguồn và tài liệu"}>
      <div className="inspector-header">
        <div>
          {researchMode && <p className="eyebrow">Inspector</p>}
          <h2>{researchMode ? (run ? `Run ${run.run_id.slice(-6)}` : "No active run") : "Nguồn và tài liệu"}</h2>
        </div>
        {researchMode ? <StatusBadge status={run?.status} /> : <ProductInspectorStatus status={run?.status} />}
      </div>
      <div className="inspector-tabs" role="tablist" aria-label="Run details">
        {visibleTabs.map((tab) => (
          <button
            className={selectedTab === tab.id ? "inspector-tab inspector-tab-active" : "inspector-tab"}
            type="button"
            role="tab"
            aria-selected={selectedTab === tab.id}
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="inspector-content">
        {selectedTab === "evidence" && <EvidencePanel run={run} researchMode={researchMode} />}
        {selectedTab === "sources" && <SourcesPanel sources={sources} researchMode={researchMode} />}
        {researchMode && selectedTab === "metrics" && <MetricsPanel run={run} />}
      </div>
      {researchMode && run && (
        <div className="inspector-footer">
          <span>{run.provider ?? "provider unknown"}</span>
          <span>{run.model ?? "model unknown"}</span>
        </div>
      )}
    </aside>
  );
}
