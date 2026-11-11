import type { SourceImportResult } from "../../types/api";
import { ProductComposer } from "./ProductComposer";
import "./product-content.css";

interface ProductHomeViewProps {
  hasReadySources: boolean;
  isRunning: boolean;
  isImporting: boolean;
  sourceNotice: string | null;
  importError?: string | null;
  onSubmit: (message: string) => Promise<void>;
  onImport: (file: File) => Promise<SourceImportResult | null>;
}

export function ProductHomeView({
  hasReadySources,
  isRunning,
  isImporting,
  sourceNotice,
  importError = null,
  onSubmit,
  onImport,
}: ProductHomeViewProps) {
  return (
    <main className="product-page product-home" aria-labelledby="product-home-title">
      <section className="product-home-intro">
        <h1 id="product-home-title">Hôm nay bạn muốn hỏi gì?</h1>
        <p className="product-home-helper">
          Hỏi về tài liệu của bạn hoặc đính kèm tệp để bắt đầu.
        </p>
        <ProductComposer
          className="product-composer-home"
          questionLabel="Câu hỏi của bạn"
          isRunning={isRunning}
          isImporting={isImporting}
          sourceNotice={sourceNotice}
          importError={importError}
          onSubmit={onSubmit}
          onImport={onImport}
        />
      </section>
    </main>
  );
}
