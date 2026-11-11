import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, ownerScopedRetrieval } from "../lib/api";
import { bootstrapWorkspace } from "./sessionBootstrap.mjs";
import { buildChatRequest, messagesForConversation } from "./chatModel.mjs";
import type {
  ConversationDetail,
  ConversationSummary,
  HealthResponse,
  RunListItem,
  RunRecord,
  SourceImportResult,
  SourceSummary,
} from "../types/api";

const SESSION_EXPIRED_MESSAGE = "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại để tiếp tục.";

function messageForError(cause: unknown, fallback: string, researchMode: boolean): string {
  if (cause instanceof ApiError && cause.status === 401) {
    return researchMode ? "Your session expired. Sign in again to continue." : SESSION_EXPIRED_MESSAGE;
  }
  if (cause instanceof ApiError && cause.status === 415 && cause.message === "UNSUPPORTED_DOCUMENT_TYPE") {
    return researchMode
      ? "Unsupported file type. Choose TXT, Markdown, or a text-readable PDF."
      : "Định dạng tệp chưa được hỗ trợ. Hãy chọn TXT, Markdown hoặc PDF có thể trích xuất văn bản.";
  }
  return cause instanceof Error ? cause.message : fallback;
}

export type InspectorTab = "evidence" | "sources" | "metrics";

export interface ResearchAppState {
  currentUser: { user_id: string; email?: string | null; username?: string | null; role: string } | null;
  isAuthenticated: boolean;
  health: HealthResponse | null;
  sources: SourceSummary[];
  history: RunListItem[];
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  activeConversation: ConversationDetail | null;
  conversationRuns: Record<string, RunRecord>;
  activeRun: RunRecord | null;
  pendingQuestion: string | null;
  activeTab: InspectorTab;
  isBooting: boolean;
  isRunning: boolean;
  isImporting: boolean;
  error: string | null;
  sourceNotice: string | null;
  setActiveTab: (tab: InspectorTab) => void;
  startNewRun: () => void;
  startNewConversation: () => void;
  submitQuestion: (message: string, condition: string, provider: string) => Promise<void>;
  selectRun: (runId: string) => Promise<void>;
  selectConversation: (conversationId: string) => Promise<void>;
  importSource: (file: File) => Promise<SourceImportResult | null>;
  dismissError: () => void;
}
export function useResearchApp({ researchMode = false }: { researchMode?: boolean } = {}): ResearchAppState {
  const [currentUser, setCurrentUser] = useState<ResearchAppState["currentUser"]>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [history, setHistory] = useState<RunListItem[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeConversation, setActiveConversation] = useState<ConversationDetail | null>(null);
  const [conversationRuns, setConversationRuns] = useState<Record<string, RunRecord>>({});
  const [activeRun, setActiveRun] = useState<RunRecord | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<InspectorTab>("evidence");
  const [isBooting, setIsBooting] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceNotice, setSourceNotice] = useState<string | null>(null);
  const conversationRequestId = useRef(0);
  const activeConversationIdRef = useRef<string | null>(null);
  activeConversationIdRef.current = activeConversationId;

  const refreshSources = useCallback(async () => {
    const response = await ownerScopedRetrieval.listSources();
    setSources(response.sources ?? []);
  }, []);

  const refreshHistory = useCallback(async () => {
    setHistory(await ownerScopedRetrieval.listRuns());
  }, []);

  const refreshConversations = useCallback(async () => {
    setConversations(await api.listConversations());
  }, []);

  const expireSession = useCallback(() => {
    setCurrentUser(null);
    setIsAuthenticated(false);
    setSources([]);
    setHistory([]);
    setConversations([]);
    setActiveConversationId(null);
    setActiveConversation(null);
    setConversationRuns({});
    setActiveRun(null);
    setError(researchMode ? "Your session expired. Sign in again to continue." : SESSION_EXPIRED_MESSAGE);
  }, [researchMode]);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      setIsBooting(true);
      try {
        const result = await bootstrapWorkspace(api, { researchMode });
        if (cancelled) return;

        setCurrentUser(result.user);
        setIsAuthenticated(result.authenticated);
        if (!result.authenticated) {
          setSources([]);
          setHistory([]);
          setConversations([]);
          if (result.sessionExpired) {
            setError(researchMode ? "Your session expired. Sign in again to continue." : SESSION_EXPIRED_MESSAGE);
          }
        }
        if (result.health.status === "fulfilled") setHealth(result.health.value);
        if (result.sources?.status === "fulfilled") setSources(result.sources.value.sources ?? []);
        if (result.history?.status === "fulfilled") setHistory(result.history.value);
        if (result.conversations?.status === "fulfilled") setConversations(result.conversations.value);

        const navigation = researchMode ? result.history : result.conversations;
        const failed = [result.health, result.sources, navigation].find(
          (item) => item?.status === "rejected",
        );
        if (failed?.status === "rejected") {
          if (failed.reason instanceof ApiError && failed.reason.status === 401) {
            expireSession();
          }
          setError(messageForError(failed.reason, researchMode ? "Backend unavailable" : "Không thể kết nối máy chủ. Vui lòng thử lại.", researchMode));
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Unable to restore the session");
      } finally {
        if (!cancelled) setIsBooting(false);
      }
    }

    void boot();
    return () => {
      cancelled = true;
    };
  }, [expireSession, researchMode]);

  const selectConversation = useCallback(async (conversationId: string) => {
    const requestId = ++conversationRequestId.current;
    activeConversationIdRef.current = conversationId;
    setActiveConversationId(conversationId);
    setActiveConversation(null);
    setConversationRuns({});
    setActiveRun(null);
    setPendingQuestion(null);
    setError(null);
    try {
      const conversation = await api.getConversation(conversationId);
      if (conversation.conversation_id !== conversationId) throw new Error("Conversation response did not match the selected conversation");
      if (requestId !== conversationRequestId.current) return;
      const messages = messagesForConversation(conversation, conversationId);
      setActiveConversation({ ...conversation, messages });
      const runIds = [...new Set(messages
        .filter((message) => message.role === "ASSISTANT" && message.run_id)
        .map((message) => message.run_id as string))];
      const settledRuns = await Promise.allSettled(runIds.map((runId) => ownerScopedRetrieval.getRun(runId)));
      if (requestId !== conversationRequestId.current) return;
      const runs = Object.fromEntries(settledRuns.flatMap((result) =>
        result.status === "fulfilled" ? [[result.value.run_id, result.value]] : []));
      setConversationRuns(runs);
      const latestRunId = [...messages].reverse().find((message) => message.role === "ASSISTANT" && message.run_id)?.run_id;
      setActiveRun(latestRunId ? runs[latestRunId] ?? null : null);
      setActiveTab("evidence");
    } catch (cause) {
      if (requestId !== conversationRequestId.current) return;
      if (cause instanceof ApiError && cause.status === 401) expireSession();
      setError(messageForError(cause, researchMode ? "Unable to load this conversation" : "Không thể mở cuộc trò chuyện này. Vui lòng thử lại.", researchMode));
      activeConversationIdRef.current = null;
      setActiveConversationId(null);
      setActiveConversation(null);
    }
  }, [expireSession, researchMode]);

  const submitQuestion = useCallback(
    async (message: string, condition: string, provider: string) => {
      const normalizedMessage = message.trim();
      if (!normalizedMessage) return;
      setIsRunning(true);
      setPendingQuestion(normalizedMessage);
      setError(null);
      try {
        const run = await api.chat(buildChatRequest({
          message: normalizedMessage,
          conversationId: researchMode ? null : activeConversationIdRef.current,
          researchMode,
          condition,
          provider,
        }));
        setActiveRun(run);
        setActiveTab("evidence");
        if (researchMode) {
          await Promise.all([refreshHistory(), refreshSources()]);
        } else {
          if (run.conversation_id) await selectConversation(run.conversation_id);
          await Promise.all([refreshConversations(), refreshSources()]);
        }
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 401) expireSession();
        setError(messageForError(cause, researchMode ? "Unable to run the research pipeline" : "Chưa thể xử lý câu hỏi này. Vui lòng thử lại.", researchMode));
        throw cause;
      } finally {
        setIsRunning(false);
        setPendingQuestion(null);
      }
    },
    [expireSession, refreshConversations, refreshHistory, refreshSources, researchMode, selectConversation],
  );

  const selectRun = useCallback(async (runId: string) => {
    setPendingQuestion(null);
    setError(null);
    try {
      setActiveRun(await ownerScopedRetrieval.getRun(runId));
      setActiveTab("evidence");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) expireSession();
      setError(messageForError(cause, researchMode ? "Unable to load this run" : "Không thể mở chi tiết câu trả lời này. Vui lòng thử lại.", researchMode));
    }
  }, [expireSession, researchMode]);

  const importSource = useCallback(async (file: File) => {
    setIsImporting(true);
    setError(null);
    setSourceNotice(null);
    try {
      const result = await api.importFile(file);
      const sourceName = result.source_name ?? file.name;
      setSourceNotice(researchMode ? `${sourceName} added to the corpus.` : `Đã thêm ${sourceName} vào tài liệu.`);
      await refreshSources();
      return result;
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) expireSession();
      setError(messageForError(cause, researchMode ? "Unable to import this source" : "Không thể thêm tài liệu này. Vui lòng thử lại.", researchMode));
      return null;
    } finally {
      setIsImporting(false);
    }
  }, [expireSession, refreshSources, researchMode]);

  return {
    currentUser,
    isAuthenticated,
    health,
    sources,
    history,
    conversations,
    activeConversationId,
    activeConversation,
    conversationRuns,
    activeRun,
    pendingQuestion,
    activeTab,
    isBooting,
    isRunning,
    isImporting,
    error,
    sourceNotice,
    setActiveTab,
    startNewRun: () => {
      conversationRequestId.current += 1;
      setActiveRun(null);
      setPendingQuestion(null);
      setError(null);
      setSourceNotice(null);
    },
    startNewConversation: () => {
      conversationRequestId.current += 1;
      activeConversationIdRef.current = null;
      setActiveConversationId(null);
      setActiveConversation(null);
      setConversationRuns({});
      setActiveRun(null);
      setPendingQuestion(null);
      setError(null);
      setSourceNotice(null);
    },
    submitQuestion,
    selectRun,
    selectConversation,
    importSource,
    dismissError: () => setError(null),
  };
}
