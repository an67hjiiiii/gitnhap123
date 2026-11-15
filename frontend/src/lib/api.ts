import type {
  ConversationDetail,
  ConversationSummary,
  HealthResponse,
  OwnerScopedRetrievalClient,
  RunListItem,
  RunRecord,
  SourceChunk,
  SourceDetail,
  SourceImportResult,
  SourcesResponse,
} from "../types/api";
import { contextOfPath, friendlyMessage } from "./errorMessage";

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: string;

  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      credentials: init?.credentials ?? "same-origin",
    });
  } catch (error) {
    const timeout = error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError");
    throw new ApiError(friendlyMessage(timeout ? { timeout: true } : { network: error instanceof TypeError }), 0, error instanceof Error ? error.message : undefined);
  }
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String(payload.detail)
        : "";
    throw new ApiError(friendlyMessage({ status: response.status, detail, context: contextOfPath(path) }), response.status, detail);
  }

  return payload as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  currentSession: () =>
    request<{
      authenticated: boolean;
      user: { user_id: string; email?: string | null; username?: string | null; role: string };
    }>("/auth/session"),
  register: (body: {
    email: string;
    username?: string;
    display_name?: string;
    password: string;
  }) => request<{ user: { user_id: string; email?: string | null; role: string } }>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  login: (body: { identifier: string; password: string }) =>
    request<{
      authenticated: boolean;
      user: { user_id: string; email?: string | null; username?: string | null; role: string };
      session: { session_id: string; user_id: string; expires_at: string };
    }>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  logout: () =>
    request<{ ok: boolean; authenticated: boolean }>("/auth/logout", {
      method: "POST",
    }),
  listSources: () => request<SourcesResponse>("/sources"),
  getSource: (sourceId: string) =>
    request<SourceDetail>(`/sources/${encodeURIComponent(sourceId)}`),
  getChunk: (chunkId: string) =>
    request<SourceChunk>(`/chunks/${encodeURIComponent(chunkId)}`),
  listRuns: () => request<RunListItem[]>("/runs"),
  getRun: (runId: string) => request<RunRecord>(`/runs/${encodeURIComponent(runId)}`),
  listConversations: () => request<ConversationSummary[]>("/conversations"),
  getConversation: (conversationId: string) =>
    request<ConversationDetail>(`/conversations/${encodeURIComponent(conversationId)}`),
  chat: (body: { message: string; condition?: string; provider?: string; conversation_id?: string; product_mode?: boolean }) =>
    request<RunRecord>("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  importFile: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<SourceImportResult>("/sources/file", {
      method: "POST",
      body,
    });
  },
};

/**
 * The retrieval surface is intentionally session-bound. Keeping this narrow
 * view separate makes it harder for UI code to accidentally invent an owner
 * parameter or call an unscoped source endpoint.
 */
export const ownerScopedRetrieval: OwnerScopedRetrievalClient = {
  listSources: api.listSources,
  getSource: api.getSource,
  getChunk: api.getChunk,
  listRuns: api.listRuns,
  getRun: api.getRun,
};
