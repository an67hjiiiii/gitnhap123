import type { ConversationSummary, HealthResponse, RunListItem, SourcesResponse } from "../types/api";

type Settled<T> = PromiseSettledResult<T>;

export interface SessionBootstrapResult {
  authenticated: boolean;
  sessionExpired?: boolean;
  user: { user_id: string; email?: string | null; username?: string | null; role: string } | null;
  health: Settled<HealthResponse>;
  sources: Settled<SourcesResponse> | null;
  history: Settled<RunListItem[]> | null;
  conversations: Settled<ConversationSummary[]> | null;
}

export function bootstrapWorkspace(api: {
  currentSession: () => Promise<SessionBootstrapResult["user"] extends infer U ? { authenticated: boolean; user: NonNullable<U> } : never>;
  health: () => Promise<HealthResponse>;
  listSources: () => Promise<SourcesResponse>;
  listRuns: () => Promise<RunListItem[]>;
  listConversations: () => Promise<ConversationSummary[]>;
}, options?: { researchMode?: boolean }): Promise<SessionBootstrapResult>;
