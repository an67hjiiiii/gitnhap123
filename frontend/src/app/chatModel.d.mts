import type { ConversationDetail, ConversationSummary, RunRecord } from "../types/api";

export const NO_EVIDENCE_COPY: string;
export function researchModeFromFlag(value: string | undefined): boolean;
export function displayConversationTitle(conversation: ConversationSummary | ConversationDetail | null | undefined): string;
export function conversationSidebarItems(conversations?: Array<ConversationSummary | ConversationDetail>): Array<ConversationSummary & { label: string }>;
export function messagesForConversation(conversation: ConversationDetail | null, requestedConversationId: string | null): ConversationDetail["messages"];
export function buildChatRequest(input: { message: string; conversationId?: string | null; researchMode: boolean; condition: string; provider: string }): { message: string; conversation_id?: string; condition?: string; provider?: string; product_mode?: boolean };
export function productAnswerText(messageContent: string | undefined, run: RunRecord | null): string;
