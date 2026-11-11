import { useId, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUpIcon, PaperclipIcon, SpinnerGapIcon } from "@phosphor-icons/react";
import type { SourceImportResult } from "../../types/api";
import "./product-composer.css";

const MAX_TEXTAREA_HEIGHT = 160;
const COMPACT_TEXTAREA_HEIGHT = 40;

interface ProductComposerProps {
  className?: string;
  isRunning: boolean;
  isImporting: boolean;
  showImport?: boolean;
  sourceNotice?: string | null;
  importError?: string | null;
  questionLabel?: string;
  onSubmit: (message: string) => Promise<void>;
  onImport: (file: File) => Promise<void | SourceImportResult | null>;
}

function resizeTextarea(textarea: HTMLTextAreaElement) {
  textarea.style.height = "auto";
  const contentHeight = textarea.scrollHeight;
  const height = Math.min(contentHeight, MAX_TEXTAREA_HEIGHT);
  textarea.style.height = String(Math.max(height, COMPACT_TEXTAREA_HEIGHT)) + "px";
  textarea.style.overflowY = contentHeight > MAX_TEXTAREA_HEIGHT ? "auto" : "hidden";
}

export function ProductComposer({
  className = "",
  isRunning,
  isImporting,
  showImport = true,
  sourceNotice = null,
  importError = null,
  questionLabel = "Tin nhắn cho CAP1 AI",
  onSubmit,
  onImport,
}: ProductComposerProps) {
  const [message, setMessage] = useState("");
  const [importFailed, setImportFailed] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const submittingRef = useRef(false);
  const helpId = useId();

  useLayoutEffect(() => {
    if (textareaRef.current) resizeTextarea(textareaRef.current);
  }, [message]);

  async function submit() {
    const trimmed = message.trim();
    if (!trimmed || isRunning || submittingRef.current) return;

    submittingRef.current = true;
    setMessage("");
    try {
      await onSubmit(trimmed);
    } catch {
      // The app-level alert owns the failed request state.
    } finally {
      submittingRef.current = false;
    }
  }

  async function importFile(file: File) {
    setImportFailed(false);
    try {
      setImportFailed((await onImport(file)) === null);
    } catch {
      setImportFailed(true);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
    event.preventDefault();
    void submit();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  return (
    <div className={["product-composer-region", className].filter(Boolean).join(" ")}>
      <span id={helpId} className="sr-only">Enter để gửi. Shift + Enter để xuống dòng.</span>
      <form className="product-composer" onSubmit={handleSubmit} aria-busy={isRunning || isImporting}>
        {showImport && (
          <>
            <input
              ref={fileRef}
              className="sr-only"
              type="file"
              accept=".txt,.md,.markdown,.pdf"
              aria-label="Đính kèm tài liệu"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                if (file) void importFile(file);
                event.currentTarget.value = "";
              }}
            />
            <button
              className="product-composer-button product-composer-attachment"
              type="button"
              aria-label="Đính kèm tài liệu"
              title="Đính kèm tài liệu"
              disabled={isImporting}
              onClick={() => fileRef.current?.click()}
            >
              {isImporting
                ? <SpinnerGapIcon className="product-composer-spinner" size={18} aria-hidden="true" />
                : <PaperclipIcon size={19} aria-hidden="true" />}
            </button>
          </>
        )}
        <textarea
          ref={textareaRef}
          aria-label={questionLabel}
          aria-describedby={helpId}
          value={message}
          rows={1}
          placeholder="Nhập câu hỏi..."
          disabled={isRunning}
          onChange={(event) => setMessage(event.currentTarget.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          className="product-composer-button product-composer-send"
          type="submit"
          disabled={isRunning || !message.trim()}
          aria-label={isRunning ? "Đang gửi câu hỏi" : "Gửi câu hỏi"}
          title={isRunning ? "Đang gửi câu hỏi" : "Gửi câu hỏi"}
        >
          {isRunning
            ? <SpinnerGapIcon className="product-composer-spinner" size={19} aria-hidden="true" />
            : <ArrowUpIcon size={20} aria-hidden="true" />}
        </button>
      </form>
      {isImporting && <p className="product-home-import-feedback" role="status">Đang thêm tài liệu…</p>}
      {importFailed && !isImporting && <p className="product-home-import-feedback is-error" role="alert">{importError || "Không thể thêm tài liệu. Vui lòng thử lại."}</p>}
      {sourceNotice && !isImporting && !importFailed && <p className="product-home-import-feedback" role="status">{sourceNotice}</p>}
    </div>
  );
}
