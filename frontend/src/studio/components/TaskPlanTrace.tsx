import type { ModeExecutionResult } from '../types';

const statuses: Record<string, string> = {completed:'Hoàn thành',running:'Đang chạy',pending:'Chờ',failed:'Thất bại',blocked:'Bị chặn',cancelled:'Đã dừng'};

export function TaskPlanTrace({result}: {result: ModeExecutionResult}) {
  const plan = result.planning_trace;
  if (!plan?.execution_order?.length) return null;
  return <section aria-label="Kế hoạch nhiệm vụ và phụ thuộc" className="rounded-xl border border-slate-200 bg-white p-4 space-y-4 min-w-0">
    <div><h2 className="font-semibold text-slate-900">Kế hoạch nhiệm vụ và phụ thuộc</h2>
      <p className="text-xs text-slate-600 mt-1">Thực thi tuần tự theo DAG trên máy cục bộ. Ánh xạ yêu cầu giúp truy vết; chưa phải điểm đánh giá chất lượng.</p></div>
    <p className="text-sm text-slate-700 break-words">Thứ tự thực thi: {plan.execution_order.join(' → ')}</p>
    <ol className="grid gap-3 sm:grid-cols-2">
      {plan.execution_order.map(id => {
        const task=result.subtasks.find(item=>item.id===id);
        if (!task) return null;
        const output=result.agent_results.find(item=>item.task_id===id);
        return <li key={id} className="border border-slate-200 rounded-lg p-3 min-w-0 text-xs space-y-2">
          <p className="font-semibold text-slate-900 break-words">{id} · {task.title}</p>
          <p>{task.agent_role} · {statuses[task.status] ?? task.status}</p>
          <p>Phụ thuộc: {task.depends_on?.join(', ') || 'Không có'}</p>
          <p>Yêu cầu: {task.requirement_ids?.join(', ') || 'Chưa có ánh xạ'}</p>
          <p className="text-slate-600">{task.assignment_reason}</p>
          {(task.source_task_ids?.length ?? 0)>1 && <p>Gộp từ: {task.source_task_ids?.join(', ')}</p>}
          <details><summary className="cursor-pointer text-blue-800">Xem mô tả và đầu ra</summary>
            <p className="mt-2 whitespace-pre-wrap break-words">{task.description}</p>
            <p className="mt-2 break-words">Truy vấn: {task.retrieval_query}</p>
            <p className="mt-2">Bằng chứng lập kế hoạch: {task.evidence_ids?.length || 0} đoạn</p>
            <pre className="mt-2 whitespace-pre-wrap break-words font-sans">{output?.content ?? 'Chưa có đầu ra.'}</pre>
          </details>
        </li>;
      })}
    </ol>
    <details className="text-xs"><summary className="cursor-pointer text-blue-800">Đối chiếu yêu cầu gốc và nhật ký thực thi</summary>
      <ul className="mt-3 space-y-2">{plan.requirements?.map(r=><li key={r.id} className="break-words"><strong>{r.id}</strong> · {r.text}</li>)}</ul>
      <ul className="mt-3 space-y-1">{result.execution_trace?.map((event,index)=><li key={index}>{event.task_id} · {statuses[event.status] ?? event.status} · {event.elapsed_ms.toLocaleString('vi-VN')} ms từ đầu lượt</li>)}</ul>
    </details>
  </section>;
}
