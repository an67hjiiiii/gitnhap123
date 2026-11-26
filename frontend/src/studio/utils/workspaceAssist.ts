// Trợ giúp cho Không gian làm việc 3 cột (Đợt 2): luật cố định, không gọi mô hình.
import { progressLabel } from './progress.ts';
import type { ProgressEvent } from './progress.ts';

export type SuggestKey = 'conditions' | 'procedure' | 'approver' | 'contract_review' | 'validity';
const fold = (v: string) => v.normalize('NFD').replace(/\p{M}/gu, '').replace(/đ/gi, 'd').toLowerCase();

/** Kỹ năng đề xuất theo loại tài liệu trong phạm vi hỏi và câu đang gõ. Chỉ trả kỹ năng có đường gọi thật. */
export function suggestSkills(docTypes: (string | null | undefined)[], question = ''): { key: SuggestKey; why: string }[] {
  const types = new Set(docTypes.filter(Boolean) as string[]);
  const q = fold(question);
  const out: { key: SuggestKey; why: string }[] = [];
  const add = (key: SuggestKey, why: string) => { if (!out.some(o => o.key === key)) out.push({ key, why }); };
  if (/dieu kien|du dieu kien|co duoc|han muc/.test(q)) add('conditions', 'Câu hỏi về điều kiện');
  if (/quy trinh|cac buoc|thu tuc|lam the nao/.test(q)) add('procedure', 'Câu hỏi về quy trình');
  if (/ai duyet|phe duyet|cap duyet|tham quyen/.test(q)) add('approver', 'Câu hỏi về người duyệt');
  if (types.has('contract')) add('contract_review', 'Có hợp đồng trong phạm vi');
  if (types.has('legal_doc') || types.has('regulation')) { add('validity', 'Có văn bản quy định'); add('conditions', 'Có văn bản quy định'); }
  if (types.has('internal_rules')) { add('procedure', 'Có nội quy'); add('approver', 'Có nội quy'); }
  if (types.has('internal_policy')) add('procedure', 'Có chính sách, quy trình nội bộ');
  return out.slice(0, 3);
}

type RunLike = { status?: string; condition?: string; events?: any[]; task_results?: any[]; metrics?: { input_tokens?: number; output_tokens?: number; latency_ms?: number } };

/** Quá trình xử lý của một lượt chạy: các bước (theo sự kiện thật, bỏ trùng), tác tử, token, thời gian. */
export function traceOf(run: RunLike | undefined | null) {
  if (!run) return null;
  const steps: string[] = [];
  for (const e of run.events || []) {
    const label = progressLabel(e as ProgressEvent);
    if (label && steps[steps.length - 1] !== label) steps.push(label);
  }
  const agents = [...new Set((run.task_results || []).map((r: any) => r.domain || r.agent_role).filter(Boolean))] as string[];
  const m = run.metrics || {};
  const tokens = m.input_tokens == null && m.output_tokens == null ? null : (m.input_tokens ?? 0) + (m.output_tokens ?? 0);
  return { steps, agents, tasks: (run.task_results || []).length, tokens, ms: m.latency_ms ?? null, status: run.status ?? null };
}

const STOP = new Set([
  'nhung', 'cac', 'nao', 'gom', 'la', 'gi', 'co', 'khong', 'the', 'cua', 'cho', 'trong', 've', 'va', 'duoc', 'nay',
  'mot', 'bao', 'nhieu', 'tai', 'lieu', 'hay', 'voi', 'khi', 'thi', 'de', 'ai', 'dua', 'tren', 'hien', 'biet', 'theo',
  'truoc', 'sau', 'tu', 'den', 'nguoi', 'hang', 'thang', 'ngay', 'nam', 'muc', 'tong', 'chinh', 'sach', 'cung', 'nhu',
  'neu', 'ma', 'da', 'se', 'dang', 'phai', 'can', 'boi', 'tai', 'vi', 'ra', 'vao', 'len', 'xuong', 'moi', 'tat', 'ca',
]);

/** Từ khóa của câu hỏi để tô trong đoạn trích (ưu tiên cụm từ ghép 2 tiếng liền kề để tránh tô nhầm tiếng đơn như 'lợi' trong 'phúc lợi'). */
export function keyTerms(question: string): string[] {
  const rawTokens = question
    .split(/[^\p{L}\p{N}]+/u)
    .filter(w => w.length >= 2)
    .map(w => ({ raw: w, folded: fold(w), stop: STOP.has(fold(w)) }));

  const phrases: string[] = [];
  const usedInPhrase = new Set<number>();

  // Ghép các cặp từ nội dung liền kề (không phải số thuần) thành cụm 2 tiếng chuẩn tiếng Việt (vd: "loi nhuan", "doanh thu", "bao hiem")
  for (let i = 0; i < rawTokens.length - 1; i += 1) {
    const a = rawTokens[i];
    const b = rawTokens[i + 1];
    if (a.stop || b.stop) continue;
    if (/^\d+$/.test(a.folded) || /^\d+$/.test(b.folded)) continue;
    // Bỏ qua nếu một trong hai là tên riêng/viết tắt tiếng Anh/mã dài >= 6 hoặc viết hoa toàn bộ (vd. VietCore, CSDL)
    if (a.raw.length >= 6 || b.raw.length >= 6 || a.raw === a.raw.toUpperCase() || b.raw === b.raw.toUpperCase()) continue;
    phrases.push(`${a.folded} ${b.folded}`);
    usedInPhrase.add(i);
    usedInPhrase.add(i + 1);
  }

  const singles: string[] = [];
  for (let i = 0; i < rawTokens.length; i += 1) {
    const t = rawTokens[i];
    if (t.stop) continue;
    // Giữ từ đơn khi không bị cắt lẻ từ cụm ghép, HOẶC là số/năm/viết tắt/tên riêng
    if (!usedInPhrase.has(i) || /\d/.test(t.folded) || t.raw === t.raw.toUpperCase()) {
      singles.push(t.folded);
    }
  }

  return [...new Set([...phrases, ...singles])].slice(0, 14);
}

/** Cắt đoạn văn thành phần thường / phần tô theo cụm từ & từ khóa (so không dấu, ưu tiên cụm dài trước, giữ nguyên chữ gốc). */
export function highlightParts(text: string, terms: string[]): { t: string; hit: boolean }[] {
  if (!terms.length || !text) return [{ t: text, hit: false }];

  // Tách văn bản thành dãy token (từ và phần ngăn cách) để khớp cụm từ theo đúng ranh giới từ
  const rawSegs = text.split(/([\p{L}\p{N}]+)/u).filter(Boolean);
  const segs = rawSegs.map(s => ({
    raw: s,
    isWord: /^[\p{L}\p{N}]+$/u.test(s),
    folded: /^[\p{L}\p{N}]+$/u.test(s) ? fold(s) : '',
  }));

  const wordIndices: number[] = [];
  segs.forEach((s, idx) => { if (s.isWord) wordIndices.push(idx); });

  const phraseList = terms
    .map(t => t.trim().split(/\s+/).filter(Boolean))
    .filter(p => p.length >= 2)
    .sort((a, b) => b.length - a.length);
  const singleSet = new Set(terms.filter(t => !/\s/.test(t)));

  const hitSeg = new Array<boolean>(segs.length).fill(false);

  // 1. Ưu tiên khớp cụm từ ghép nhiều tiếng liền nhau (chỉ cách nhau bởi khoảng trắng đơn giản)
  for (let wi = 0; wi < wordIndices.length; wi += 1) {
    for (const phrase of phraseList) {
      if (wi + phrase.length > wordIndices.length) continue;
      let ok = true;
      for (let k = 0; k < phrase.length; k += 1) {
        const curSegIdx = wordIndices[wi + k];
        if (segs[curSegIdx].folded !== phrase[k]) { ok = false; break; }
        if (k > 0) {
          const prevSegIdx = wordIndices[wi + k - 1];
          const between = segs.slice(prevSegIdx + 1, curSegIdx).map(x => x.raw).join('');
          if (!/^[\s-]+$/.test(between)) { ok = false; break; }
        }
      }
      if (ok) {
        const from = wordIndices[wi];
        const to = wordIndices[wi + phrase.length - 1];
        for (let idx = from; idx <= to; idx += 1) hitSeg[idx] = true;
        break;
      }
    }
  }

  // 2. Khớp từ đơn còn lại
  for (const idx of wordIndices) {
    if (!hitSeg[idx] && singleSet.has(segs[idx].folded)) {
      hitSeg[idx] = true;
    }
  }

  const parts: { t: string; hit: boolean }[] = [];
  for (let i = 0; i < segs.length; i += 1) {
    const hit = hitSeg[i];
    const last = parts[parts.length - 1];
    if (last && last.hit === hit) last.t += segs[i].raw;
    else parts.push({ t: segs[i].raw, hit });
  }
  return parts;
}
