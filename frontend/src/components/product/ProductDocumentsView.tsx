import { PlusIcon } from "@phosphor-icons/react";
import { useRef } from "react";
import type { SourceSummary } from "../../types/api";

interface ProductDocumentsViewProps {
  sources: SourceSummary[];
  isLoading: boolean;
  isImporting: boolean;
  error?: string | null;
  notice?: string | null;
  onImport: (file: File) => Promise<void>;
}

function formatStatus(source: SourceSummary): string {
  const status = (source.status ?? source.index_status ?? "").trim().toUpperCase();
  if (status === "READY") return "Sẵn sàng";
  if (["PROCESSING", "INDEXING", "PENDING"].includes(status)) return "Đang xử lý";
  if (["FAILED", "ERROR"].includes(status)) return "Không xử lý được";
  if (status === "PDF_NO_TEXT") return "PDF không có văn bản";
  if (status === "PDF_EXTRACTION_UNAVAILABLE") return "Không thể trích xuất PDF";
  return status || "Trạng thái chưa có";
}

export function ProductDocumentsView({ sources, isLoading, isImporting, error, notice, onImport }: ProductDocumentsViewProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  function chooseFile(file?: File) {
    if (file) void onImport(file);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <main className="product-page product-documents" aria-labelledby="product-documents-title">
      <div className="product-page-heading">
        <div><h1 id="product-documents-title">Tài liệu</h1><p>Quản lý các nguồn có thể dùng để trả lời.</p></div>
        <button className="product-primary-button" type="button" disabled={isImporting} onClick={() => inputRef.current?.click()}><PlusIcon size={17} aria-hidden="true" />{isImporting ? "Đang tải lên…" : "Thêm tài liệu"}</button>
        <input ref={inputRef} className="sr-only" type="file" accept=".txt,.md,.markdown,.pdf" aria-label="Chọn tệp TXT, Markdown hoặc PDF có văn bản" onChange={(event) => chooseFile(event.target.files?.[0])} />
      </div>
      <p className="product-supported-files">Hỗ trợ TXT, Markdown và PDF có thể trích xuất văn bản.</p>
      {error && <p className="product-error-state" role="alert">{error}</p>}
      {notice && <p className="product-success-state" role="status">{notice}</p>}
      <section className="product-document-list" aria-label="Tài liệu trong không gian của bạn" aria-busy={isLoading || isImporting}>
        <div className="product-document-list-heading"><span>Tên tài liệu</span><span>Trạng thái</span><span>Loại</span></div>
        {isLoading ? <p className="product-inline-state" role="status">Đang tải tài liệu…</p> : sources.length === 0 ? (
          <div className="product-empty-panel"><h2>Chưa có tài liệu</h2><p>Tải lên tệp TXT, Markdown hoặc PDF có văn bản để bắt đầu.</p><button className="product-secondary-button" type="button" disabled={isImporting} onClick={() => inputRef.current?.click()}>Chọn tài liệu</button></div>
        ) : sources.map((source) => {
          const raw = (source.status ?? source.index_status ?? "unknown").toLowerCase();
          return <article className="product-document-list-row" key={source.source_id}><span className="product-document-name">{source.source_name}</span><span className={`product-source-status status-${raw}`}>{formatStatus(source)}</span><span className="product-document-format">{source.source_format?.toUpperCase() ?? source.source_type ?? "Tài liệu"}</span></article>;
        })}
      </section>
    </main>
  );
}
