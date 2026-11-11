import type { AgentResult } from '../types';

// Các tab theo vai trò phải giữ toàn bộ nhiệm vụ, không chỉ kết quả đầu tiên.
export function groupAgentResults(results: AgentResult[] | undefined, role: string): AgentResult | undefined {
  const tasks = results?.filter(result => result.agent_role === role) ?? [];
  if (!tasks.length) return undefined;
  return {
    agent_role: role,
    subtask_title: `${tasks.length} nhiệm vụ · ${role}`,
    latency_ms: Math.round(tasks.reduce((sum, task) => sum + task.latency_ms, 0) * 100) / 100,
    tokens_used: tasks.reduce((sum, task) => sum + task.tokens_used, 0),
    content: tasks.map(task => `### ${task.task_id ?? ''} — ${task.subtask_title}\n${task.content}`).join('\n\n'),
    relevant_chunks: tasks.flatMap(task => task.relevant_chunks),
  };
}
