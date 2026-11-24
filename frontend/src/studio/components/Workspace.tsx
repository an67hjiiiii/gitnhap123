import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUp, Bot, BookOpen, Check, ChevronDown, Wrench, Paperclip, PanelRight, Pencil, RotateCcw, Archive, ListChecks, CornerDownRight, Link2, X, FileDown, FileText, Footprints, Inbox, MessageSquareText, Mic, Microscope, RefreshCw, Sparkles, Square, Upload, Users, Volume2, Zap } from 'lucide-react';
import { ChatStreamEvent, chatScope, saveSkillCard, routeSkill, runSkill, SKILL_LIST, SkillKey, SkillOutput, SkillRoute, ConversationMessage, getChunk, getConversation, getRawRun, sendAnalysis, sendChat, explainFailure, getDocuments, GroundingResult, listFeedback, listReports, getReport, Rating, answerReport, saveReport, exportDocx, canSaveReports, ocrImage } from '../services/api';
import { FileIcon } from './FileIcon';
import { WorkspaceContext, CtxTab } from './WorkspaceContext';
import { DocumentReader } from './DocumentReader';
import { saveBlob } from './analysis/exporters';
import { ExportButtons } from './analysis/exporters';
import { AnswerFeedback, GroundingButton, GroundingPanel } from './AnswerTools';
import { adaptRun, answerText, Cap1Run, CONDITION_LABEL } from '../services/adapt';
import { Markdown } from '../utils/markdown';
import { serverDate } from '../utils/time';
import { AssistantRobot } from './robot/AssistantRobot';
import { useRobotAssistant } from './robot/RobotContext';
import { RobotState } from './robot/robotEngine';
import { PIPELINE_STEPS, PipelineStep } from './ExecutionFlowGraph';
import { OfficePanel, readOfficePref, type OfficeMode, type OfficeSource } from '../office3d/OfficePanel';
import { endLive, getLive, pushLive, startLive } from '../office3d/liveBus';
import { RunTimeline } from '../office3d/RunTimeline';
import { buildTimeline, timelineOf } from '../office3d/timeline';
import { NodeTraceModal } from './NodeTraceModal';
import { StudioModal } from './StudioModal';
import { ModeExecutionResult } from '../types';
import { motionAllowed } from '../utils/motion';
import { burstBubbles } from '../utils/bubbles';
import { citeLabel, inlineCites } from '../utils/citations';
import { SkillCard } from './SkillCard';
import { parseSkillMessage, summarizeSkill } from '../utils/skillMessage';
import { progressLabel } from '../utils/progress';


// Không gian làm việc duy nhất: hỏi nhanh (nhiều lượt) và phân tích sâu (A/B/C, 8 bước) trong cùng một cuộc trò chuyện.
type Mode = 'quick' | 'A' | 'B' | 'C';
const MODE_INFO: Record<Mode, { label: string; hint: string }> = {
  quick: { label: 'Tự động', hint: 'Hệ thống tự chọn: trả lời thẳng, gọi một kỹ năng hay chia việc cho các tác tử. Gõ "/" để chọn kỹ năng.' },
  A: { label: 'Vanilla RAG', hint: 'Điều kiện A: một lượt truy xuất, một lần sinh.' },
  B: { label: 'Multi-Agent cơ bản', hint: 'Điều kiện B: chia việc, chưa tối ưu.' },
  C: { label: 'Điều phối đầy đủ', hint: 'Điều kiện C: lập kế hoạch có kiểm tra, chuẩn hóa, tối ưu ngữ cảnh.' },
};
const REASK = [
  { agent: 'conditions', label: 'Xét điều kiện (ai được gì, đủ điều kiện không)' }, { agent: 'procedure', label: 'Các bước làm và cấp duyệt' },
  { agent: 'terms', label: 'Điều khoản, quyền và nghĩa vụ' }, { agent: 'figures', label: 'Tính số liệu (bao nhiêu, tỷ lệ)' },
];
const STATUS_LABEL: Record<string, string> = { COMPLETE: 'Đủ bằng chứng', PARTIAL: 'Một phần', NO_EVIDENCE: 'Không có bằng chứng', FAILED: 'Thất bại' };
// Viết dạng câu hỏi để CAP1 đi đường hỏi đáp trực tiếp (câu mệnh lệnh bị chuyển sang lập kế hoạch nhiều bước).
const PRESETS = [
  { label: 'Tóm tắt ý chính', text: 'Tài liệu nói về những ý chính nào?' },
  { label: 'Quy trình gồm bước nào?', text: 'Quy trình này gồm những bước nào, ai phụ trách từng bước?' },
  { label: 'Điều kiện, hạn mức', text: 'Có những điều kiện, hạn mức hoặc thời hạn nào cần lưu ý?' },
  { label: 'Ai được phê duyệt?', text: 'Ai có quyền phê duyệt việc này?' },
  { label: 'Giải thích thuật ngữ', text: 'Những thuật ngữ quan trọng trong tài liệu có nghĩa là gì?' },
  { label: 'Lỗi thường gặp', text: 'Lỗi thường gặp nào cần lưu ý?' },
]

// Nguồn đã hiện thành nút bên dưới nên bỏ dòng "Nguồn: [...]" trong thân câu trả lời.
const stripSources = (t: string) => t.replace(/\n?\s*Nguồn:\s*(\[[^\]]+\][,\s]*)+$/u, '').trim();
// Ảnh dán vào ô chat (21/11): chữ nhận dạng được gửi kèm câu hỏi sau dấu này; khung tin nhắn tách ra để hiện gọn.
const IMG_MARK = '[Ảnh đính kèm, chữ nhận dạng được]:';
const splitAsk = (t: string) => { const at = t.indexOf(IMG_MARK); return at < 0 ? { ask: t, ocr: '' } : { ask: t.slice(0, at).trim(), ocr: t.slice(at + IMG_MARK.length).trim() }; };
// ảnh dán có thể là webp/bmp: vẽ lại thành PNG để máy chủ (Tesseract) đọc được; ảnh chụp màn hình nhỏ phóng 2 lần cho đúng dấu hơn
const toPng = async (blob: Blob): Promise<Blob> => {
  const bmp = await createImageBitmap(blob);
  const k = bmp.width < 1400 ? 2 : 1;
  const c = document.createElement('canvas'); c.width = bmp.width * k; c.height = bmp.height * k;
  const g = c.getContext('2d')!; g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height); g.imageSmoothingQuality = 'high';
  g.drawImage(bmp, 0, 0, c.width, c.height);
  return new Promise((ok, no) => c.toBlob(b => (b ? ok(b) : no(new Error('Không đọc được ảnh.'))), 'image/png'));
};
// Bốn chặng hiện trong lúc chờ (kiểu "Quá trình xử lý"); chặng suy ra từ sự kiện tiến trình thật của pipeline.
const PHASES = [
  { t: 'Đã nhận yêu cầu', d: 'Phân tích mục tiêu và loại tác vụ' },
  { t: 'Tìm tài liệu', d: 'Chọn các đoạn liên quan trong kho' },
  { t: 'Đối chiếu nội dung', d: 'Trích xuất, kiểm tra căn cứ' },
  { t: 'Tổng hợp kết quả', d: 'Sắp xếp và trình bày' },
];
const phaseOf = (steps: string[], answer: string) => answer ? 3
  : steps.some(st => /đoạn liên quan|đọc tài liệu|kế hoạch|giao việc|kỹ năng|: xong|Chọn tác tử/i.test(st)) ? 2 : 1;

// Nguồn tham chiếu gom theo tài liệu: biểu tượng định dạng + tên + các đoạn bấm được.
function SourceList({ cites, docs, onCite }: { cites: string[]; docs: { id?: number | string; source_file: string }[]; onCite: (id: string) => void }) {
  const groups: { key: string; name: string; parts: { id: string; n: string }[] }[] = [];
  for (const id of cites) {
    const m = id.match(/^(.*)_c(\d+)$/);
    const doc = m ? docs.find(d => String(d.id) === m[1]) : undefined;
    const key = doc ? m![1] : id;
    let g = groups.find(x => x.key === key);
    if (!g) groups.push(g = { key, name: doc?.source_file ?? '', parts: [] });
    g.parts.push({ id, n: doc ? `đoạn ${Number(m![2]) + 1}` : citeLabel(id, docs) });
  }
  return <div className="ws-srcs"><span className="ws-srcs-h"><Link2 size={14} />Nguồn tham chiếu</span>
    <div className="ws-srcs-list">{groups.map(g => (
      <div key={g.key} className="ws-src">
        <FileIcon name={g.name || 'tai-lieu'} size={22} />
        <div><b title={g.name || g.key}>{g.name ? g.name.replace(/\.[^.]+$/, '').replace(/_/g, ' ') : 'Tài liệu ngoài không gian này'}</b>
          <span>{g.parts.map(p => <button key={p.id} type="button" onClick={() => onCite(p.id)} title={`Xem đoạn tài liệu (${p.id})`}>{p.n}</button>)}</span></div>
      </div>))}</div></div>;
}
const isPlanRejected = (run?: Cap1Run) => run?.status === 'FAILED' && /failed verification/i.test(String(run?.answer ?? ''));
const isQuick = (run?: Cap1Run) => !!run?.events?.some((e: any) => e.stage === 'product_request_routing');
const citationsOf = (run?: Cap1Run) => [...new Set((run?.task_results || []).flatMap((r: any) => r.citations || []))] as string[];
const ago = (iso?: string) => {
  if (!iso) return '';
  const m = Math.round((Date.now() - serverDate(iso).getTime()) / 60000);
  return m < 1 ? 'vừa xong' : m < 60 ? `${m} phút trước` : m < 1440 ? `${Math.round(m / 60)} giờ trước` : `${Math.round(m / 1440)} ngày trước`;
};
const firstName = (name?: string) => name?.trim().split(/\s+/).slice(-1)[0];
// Văn bản để đọc to: bỏ mã đoạn, ký hiệu markdown và dòng nguồn.
const speakable = (t: string) => stripSources(t).replace(/\[?src_[0-9a-f]+_c\d+\]?/gi, '').replace(/^\s*[#>|*-]+\s*/gm, '').replace(/[*`|_]+/g, ' ').replace(/\s+/g, ' ').trim();
const Recognition: any = typeof window !== 'undefined' ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition : undefined;
const busy = (s: RobotState) => !['idle', 'happy', 'completed', 'error', 'sleeping', 'speaking'].includes(s);

// Lời thoại hiện dần từng chữ; tôn trọng giảm chuyển động.
function useTyped(text: string) {
  const [shown, setShown] = useState(text);
  useEffect(() => {
    if (!motionAllowed()) { setShown(text); return; }
    let i = 0; setShown('');
    const t = window.setInterval(() => { i += 2; setShown(text.slice(0, i)); if (i >= text.length) window.clearInterval(t); }, 18);
    return () => window.clearInterval(t);
  }, [text]);
  return shown;
}

interface WorkspaceProps {
  workspaceId: number | string;
  conversationId: string | null;
  onConversation: (id: string | null) => void;
  onChanged: () => void;
  userName?: string;
  /** Số liệu kho đang mở và lối tắt cho màn hình đầu. */
  docs?: { id?: number | string; source_file: string; chunks_count: number; doc_type?: string | null }[];
  docCount?: number;
  chunkCount?: number;
  modelOk?: boolean;
  workspaceName?: string;
  recent?: { conversation_id: string; title: string; updated_at: string }[];
  onSeed?: (pack?: string) => void;
  onUploadFile?: (file: File) => void | Promise<void>;
  /** Câu hỏi điền sẵn từ trang khác (ví dụ Hồ sơ tài liệu → Hỏi ngay); key đổi mỗi lần để điền lại. */
  prefill?: { text: string; key: number; sourceId?: string; sourceName?: string } | null;
  onOpenToolkit?: () => void;  // đợt 6: bộ công cụ theo ngành mở bằng "/" (không còn trên thanh bên)
  /** Tài liệu vừa nạp: màn hình đầu đề nghị tạo câu hỏi gợi ý từ tài liệu này. */
  freshDoc?: { id: string; name: string } | null;
  /** quản lý kho (tải lên có mức mật, xóa, soi đoạn) đặt trong cột phải */
  manage?: React.ReactNode;
}

export const Workspace: React.FC<WorkspaceProps> = ({ workspaceId, conversationId, onConversation, onChanged, userName, docs = [], docCount = 0, chunkCount = 0, modelOk, workspaceName, recent = [], onUploadFile, prefill, onOpenToolkit, manage }) => {
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [runs, setRuns] = useState<Record<string, Cap1Run>>({});
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState<Mode>('quick');
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<{ text: string; mode: Mode; image?: string } | null>(null);
  // ảnh dán bằng Ctrl+V, chờ gửi cùng câu hỏi
  const [image, setImage] = useState<{ blob: Blob; url: string } | null>(null);
  const [pasting, setPasting] = useState(false);  // ảnh đang chuyển sang PNG: chưa cho gửi kẻo câu hỏi đi thiếu ảnh
  const [elapsed, setElapsed] = useState(0);
  // tiến trình gửi dần từ /api/chat/stream: các bước đã qua và chữ trả lời đang viết
  const [live, setLive] = useState<{ steps: string[]; answer: string }>({ steps: [], answer: '' });
  // thẻ kết quả kỹ năng (bản làm thử: chỉ giữ trong phiên, chưa lưu vào cuộc trò chuyện); after = số tin nhắn lúc tạo
  const [cards, setCards] = useState<{ id: number; convo: string; after: number; question: string; label: string; reason: string; out?: SkillOutput; error?: string }[]>([]);
  const [forced, setForced] = useState<SkillKey | null>(null);
  // hỏi lại khi mơ hồ: câu hỏi chờ người dùng chọn một cách hiểu (mục 3.4)
  const [clarify, setClarify] = useState<{ text: string; question: string; options: { agent: string; label: string }[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [allDocs, setAllDocs] = useState<{ id?: number | string; source_file: string }[]>([]);
  const [trace, setTrace] = useState<{ result: ModeExecutionResult; step: PipelineStep } | null>(null);
  // văn phòng 3D trực tiếp / xem lại trong bảng bên phải (Đợt 4, 23/11): nguồn cuối cùng được giữ để bảng sống khi thu gọn/đóng
  const [officeSrc, setOfficeSrc] = useState<OfficeSource | null>(null);
  const [officeMode, setOfficeMode] = useState<OfficeMode>('closed');
  const setOffice = useCallback((src: OfficeSource) => { setOfficeSrc(src); setOfficeMode('open'); }, []);
  const [agentsLive, setAgentsLive] = useState(false);  // câu hỏi đang đi qua các Agent (không phải kỹ năng): mới có gì để xem trong văn phòng
  const [agentsOf, setAgentsOf] = useState<string | null>(null);
  const [chunk, setChunk] = useState<{ id: string; source?: string; sourceId?: string; text?: string; error?: string } | null>(null);
  // cột phải (Đợt 2): tab đang mở, ngăn kéo trên điện thoại, phạm vi hỏi (rỗng = cả không gian), lượt đang xem quá trình
  const [ctxTab, setCtxTab] = useState<CtxTab>('sources');
  const [ctxOpen, setCtxOpen] = useState(false);
  // thu gọn cột phải (20/11): nhớ trên trình duyệt; tiện ích riêng của người xem
  const [ctxFold, setCtxFold] = useState(() => { try { return localStorage.getItem('orchestriq-ctx-fold') === '1'; } catch { return false; } });
  // thu gọn thì tắt luôn cờ mở kiểu điện thoại (bấm nguồn bật cờ này), nếu không cột đầy đủ rơi xuống dưới khung chat
  const foldCtx = (v: boolean) => { setCtxFold(v); if (v) setCtxOpen(false); try { localStorage.setItem('orchestriq-ctx-fold', v ? '1' : '0'); } catch { /* bỏ qua */ } };
  const [picked, setPicked] = useState<string[]>([]);
  const [focusRun, setFocusRun] = useState<string | null>(null);
  const [fullDoc, setFullDoc] = useState<{ id: string; name?: string } | null>(null);
  const [lastAsk, setLastAsk] = useState('');
  const [saved, setSaved] = useState<Record<string, string>>({});
  // Đợt 8: chọn lại cách hiểu → gửi lại với tác tử đó; máy chủ lưu làm ví dụ cho lần sau (chỉ ô chat sản phẩm)
  const [reask, setReask] = useState<string | null>(null);
  const [ratings, setRatings] = useState<Record<string, Rating>>({});
  const [groundOf, setGroundOf] = useState<string | null>(null);
  const [groundCache, setGroundCache] = useState<Record<string, GroundingResult | string>>({});
  const [suggested, setSuggested] = useState<{ question: string; source: string }[]>([]);
  const [only, setOnly] = useState<{ id: string; name: string } | null>(null);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState<string | null>(null);
  const [viVoice, setViVoice] = useState(false);
  const [report, setReport] = useState<{ runId: string; data?: { title: string; markdown: string; tokens: number; ms: number }; error?: string } | null>(null);
  const recRef = useRef<any>(null);
  const spokenAsk = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const closedH = useRef(0);
  const endRef = useRef<HTMLDivElement>(null);
  const skipLoad = useRef<string | null>(null);
  const { state, speechText, speak, setState } = useRobotAssistant();
  const typed = useTyped(speechText);

  const load = useCallback(async (id: string) => {
    try {
      const conv = await getConversation(id);
      setMessages(conv.messages);
      const need = conv.messages.filter(m => m.run_id).map(m => m.run_id as string).slice(-30);
      const loaded = await Promise.all(need.map(r => getRawRun(r).catch(() => null)));
      setRuns(prev => ({ ...prev, ...Object.fromEntries(loaded.filter(Boolean).map(r => [r!.run_id, r!])) }));
    } catch (err: any) { setError(err.message); }
  }, []);

  // Tên tài liệu cho nhãn trích dẫn, kể cả tài liệu thuộc không gian khác.
  useEffect(() => { getDocuments().then(setAllDocs).catch(() => setAllDocs([])); }, [docs.length]);
  useEffect(() => { listFeedback().then(f => setRatings(Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.rating])))).catch(() => {}); }, []);
  // Câu hỏi gợi ý lấy từ hồ sơ đã lập cho các tài liệu trong không gian đang mở (không gọi mô hình ở đây).
  useEffect(() => {
    const ids = new Set(docs.map(d => String(d.id ?? '')));
    if (!ids.size) { setSuggested([]); return; }
    let alive = true;
    listReports('doc_profile').then(list => Promise.all(list.slice(0, 12).map(r => getReport(r.report_id).catch(() => null)))).then(reports => {
      if (!alive) return;
      setSuggested(reports.filter(r => r && ids.has(r.payload?.source_id)).flatMap(r => (r!.payload.questions || []).slice(0, 2).map((q: any) => ({ question: q.question, source: r!.payload.source_name }))).slice(0, 6));
    }).catch(() => alive && setSuggested([]));
    return () => { alive = false; };
  }, [docs]);
  useEffect(() => {
    if (!prefill?.text) return;
    setOpen(true); setMode('quick'); setDraft(prefill.text); inputRef.current?.focus();
    setOnly(prefill.sourceId ? { id: prefill.sourceId, name: prefill.sourceName || prefill.sourceId } : null);
  }, [prefill?.key]);

  useEffect(() => {
    const synth = window.speechSynthesis; if (!synth) return;
    const check = () => setViVoice(synth.getVoices().some(v => /^vi/i.test(v.lang)));
    check(); synth.addEventListener?.('voiceschanged', check);
    return () => { synth.removeEventListener?.('voiceschanged', check); synth.cancel(); recRef.current?.abort?.(); };
  }, []);

  useEffect(() => {
    setError(null); setAgentsOf(null);
    if (!conversationId) { setMessages([]); return; }
    if (skipLoad.current === conversationId) { skipLoad.current = null; return; }
    void load(conversationId); setOpen(true);
  }, [conversationId, load]);

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); }, [messages.length, pending]);
  useEffect(() => { if (live.answer) endRef.current?.scrollIntoView({ block: 'end' }); }, [live.answer.length > 0, live.steps.length]);
  useEffect(() => {
    if (!pending) return;
    const start = performance.now(); setElapsed(0);
    const t = window.setInterval(() => setElapsed(Math.floor((performance.now() - start) / 1000)), 1000);
    return () => window.clearInterval(t);
  }, [pending]);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);
  useEffect(() => {
    const el = inputRef.current; if (!el) return;
    el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [draft, open]);

  useLayoutEffect(() => {
    const el = formRef.current;
    if (!open || !el || !closedH.current || !motionAllowed()) return;
    el.animate([{ height: `${closedH.current}px`, overflow: 'hidden' }, { height: `${el.offsetHeight}px`, overflow: 'hidden' }],
      { duration: 650, easing: 'cubic-bezier(.45,0,.2,1)' });
    closedH.current = 0;
  }, [open]);

  const expand = (e?: React.MouseEvent) => {
    if (open) return;
    if (e && motionAllowed()) burstBubbles(e.clientX, e.clientY);
    closedH.current = formRef.current?.offsetHeight ?? 0;
    setOpen(true);
    speak(`Chào ${firstName(userName) || 'bạn'}! Cứ hỏi về tài liệu, mình tự chọn cách làm: trả lời thẳng, gọi kỹ năng hay chia việc cho các tác tử.`);
  };

  const send = async (e?: React.FormEvent, again?: { text: string; agent: string }, retry?: string) => {
    e?.preventDefault();
    const typed = again?.text ?? retry ?? draft.trim();
    const img = again || retry ? null : image;
    setClarify(null);
    if ((!typed && !img) || pending || pasting) return;
    const spoken = spokenAsk.current; spokenAsk.current = false;
    setPending({ text: typed || 'Hỏi về ảnh đính kèm', mode, image: img?.url }); setDraft(''); setError(null);
    // điện thoại: tấm trượt văn phòng che nửa dưới (câu trả lời, nút chọn cách hiểu): thu về thẻ "Agent đang làm"
    const narrow = !!window.matchMedia?.('(max-width: 1023px)').matches;
    if (narrow && officeMode === 'open') setOfficeMode('collapsed');
    let text = typed;
    if (img) {
      setLive({ steps: ['Đang đọc chữ trong ảnh'], answer: '' });
      try {
        const ocr = (await ocrImage(img.blob)).trim();
        if (!ocr) throw new Error('Không nhận dạng được chữ nào trong ảnh.');
        // không gõ gì: chữ trong ảnh chính là câu hỏi (thường là ảnh chụp câu hỏi hoặc đoạn văn)
        text = typed ? `${typed}\n\n${IMG_MARK}\n${ocr.slice(0, 2000)}` : ocr.slice(0, 2000);
        setImage(null);
      } catch (err: any) {
        setError(`Chưa đọc được ảnh: ${err.message}`); setDraft(typed); setPending(null); setState('idle');
        return;
      }
    }
    setState(mode === 'quick' ? 'searching' : 'decomposing');
    speak(mode === 'quick' ? 'Đang tìm trong tài liệu…' : 'Đang lập kế hoạch và chia việc cho các tác tử…');
    try {
      const scope = only ? [only.id] : picked.length ? picked : undefined;
      setLastAsk(text); setFocusRun(null);
      if (mode === 'quick' && !again) {
        // Tự động: câu khớp rõ một kỹ năng (hoặc chọn bằng "/") thì gọi kỹ năng, không thì để pipeline tự chọn
        const ids = await chatScope(workspaceId, scope);
        const pick = forced; setForced(null);
        const r = await routeSkill(text, ids, pick ?? undefined).catch(() => ({ route: 'pipeline' } as SkillRoute));
        if (r.route === 'clarify') {
          setClarify({ text, question: r.question, options: r.options }); setState('idle'); speak(r.question);
          return;
        }
        if (r.route === 'skill') {
          setLive({ steps: [r.reason, `Đang chạy kỹ năng ${r.label}`], answer: '' });
          speak(`Mình dùng kỹ năng ${r.label} cho câu này…`);
          const card = { id: Date.now(), convo: conversationId ?? '', after: messages.length, question: text, label: r.label, reason: r.reason };
          let out: SkillOutput;
          try { out = await runSkill(r.skill, text, r.source_ids); }
          catch (err: any) { setCards(c => [...c, { ...card, error: err.message }]); setState('error'); speak('Kỹ năng chưa chạy được.'); return; }
          try {
            // lưu vào cuộc trò chuyện để tải lại trang vẫn còn; lưu không được thì vẫn hiện thẻ trong phiên
            const cid = await saveSkillCard(conversationId, text, summarizeSkill(out.skill, r.label, out.data), { skill: out.skill, label: r.label, reason: r.reason, data: out.data }, workspaceId);
            await load(cid);
            if (cid !== conversationId) { skipLoad.current = cid; onConversation(cid); }
            onChanged();
          } catch { setCards(c => [...c, { ...card, out }]); }
          setState('completed'); speak(`Xong kỹ năng ${r.label}.`);
          return;
        }
      }
      setLive({ steps: [], answer: '' });
      startLive(splitAsk(text).ask); setAgentsLive(true);
      // bảng văn phòng tự theo câu hỏi đang chạy: đang mở/thu gọn (hoặc lần trước để mở) thì chuyển sang Trực tiếp
      let pref = officeMode !== 'closed' ? officeMode : officeSrc ? 'closed' : readOfficePref().mode;
      if (pref === 'open' && narrow) pref = 'collapsed';
      if (pref !== 'closed') { setOfficeSrc({ kind: 'live' }); setOfficeMode(pref); }
      const onEvent = (e: ChatStreamEvent) => { pushLive(e); setLive(prev => {
        if (e.type === 'answer') return { ...prev, answer: e.text };
        if (e.type === 'queue') {  // máy đang trả lời người khác: báo thứ tự chờ, thay dòng chờ cũ
          const waiting = `Đang chờ lượt, thứ tự ${e.position}`;
          const rest = prev.steps.filter(st => !st.startsWith('Đang chờ lượt'));
          return { ...prev, steps: [...rest, waiting] };
        }
        const label = progressLabel(e);
        return !label || prev.steps[prev.steps.length - 1] === label ? prev : { ...prev, steps: [...prev.steps, label] };
      }); };
      let run = mode === 'quick' ? await sendChat(text, conversationId, workspaceId, scope, onEvent, again?.agent) : await sendAnalysis(text, mode, conversationId, workspaceId, scope);
      setRuns(prev => ({ ...prev, [run.run_id]: run }));
      // Kế hoạch bị bước kiểm tra của CAP1 từ chối (hành vi nghiên cứu, giữ nguyên): lượt thất bại vẫn lưu và hiện,
      // rồi trả lời lại bằng Hỏi nhanh trong cùng cuộc trò chuyện để người dùng không phải tự gửi lại.
      if (mode !== 'quick' && isPlanRejected(run)) {
        setPending({ text, mode: 'quick' }); setState('searching'); speak('Kế hoạch chưa qua bước kiểm tra, mình trả lời bằng chế độ Tự động nhé…');
        setLive({ steps: [], answer: '' });
        endLive(true);
        startLive(splitAsk(text).ask);
        const quickRun = await sendChat(text, run.conversation_id ?? conversationId, workspaceId, scope, onEvent);
        setRuns(prev => ({ ...prev, [quickRun.run_id]: quickRun }));
        run = quickRun;
      }
      endLive(run.status === 'FAILED');
      if (run.conversation_id) {
        await load(run.conversation_id);
        if (run.conversation_id !== conversationId) { skipLoad.current = run.conversation_id; onConversation(run.conversation_id); }
      }
      onChanged();
      if (run.status === 'FAILED') { setState('error'); speak('Lượt này không hoàn thành. Mình đã ghi lý do trong câu trả lời.'); }
      else {
        setState('completed'); speak(`Xong sau ${((run.metrics?.latency_ms ?? 0) / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây.`);
        // Hỏi bằng giọng nói thì đọc to câu trả lời.
        if (spoken && run.status !== 'NO_EVIDENCE') readAloud(run.run_id, answerText(run.answer as any));
      }
    } catch (err: any) {
      endLive(true);
      setError(err.message); setDraft(text); setState('error'); speak('Có lỗi khi gửi. Bạn thử lại nhé.');
    } finally { setPending(null); setAgentsLive(false); }
  };

  const listen = () => {
    if (listening) { recRef.current?.stop(); return; }
    const rec = new Recognition();
    rec.lang = 'vi-VN'; rec.interimResults = true; rec.continuous = false;
    const base = draft.trim() ? `${draft.trim()} ` : '';
    rec.onresult = (e: any) => { let t = ''; for (let i = 0; i < e.results.length; i++) t += e.results[i][0].transcript; setDraft(base + t); spokenAsk.current = true; };
    rec.onerror = (e: any) => {
      if (e.error === 'aborted') return;
      setError(e.error === 'not-allowed' || e.error === 'service-not-allowed' ? 'Trình duyệt chưa được cấp quyền dùng micro.'
        : e.error === 'no-speech' ? 'Chưa nghe thấy giọng nói. Bấm micro rồi nói lại.'
        : e.error === 'network' ? 'Trình duyệt cần kết nối mạng để nhận dạng giọng nói; hãy gõ câu hỏi.' : `Không nhận dạng được giọng nói (${e.error}).`);
    };
    rec.onend = () => { setListening(false); inputRef.current?.focus(); };
    recRef.current = rec; setError(null); setOpen(true);
    try { rec.start(); setListening(true); speak('Mình đang nghe, bạn nói câu hỏi nhé.'); } catch (err: any) { setError(err.message); }
  };
  const readAloud = (id: string, text: string) => {
    const synth = window.speechSynthesis; if (!synth) return;
    synth.cancel();
    if (speaking === id) { setSpeaking(null); return; }
    const u = new SpeechSynthesisUtterance(speakable(text));
    u.lang = 'vi-VN'; const v = synth.getVoices().find(x => /^vi/i.test(x.lang)); if (v) u.voice = v;
    u.onend = u.onerror = () => setSpeaking(s => (s === id ? null : s));
    setSpeaking(id); synth.speak(u);
  };
  const openReport = async (runId: string, again = false) => {
    if (!again && report?.runId === runId && report.data) return;
    setReport({ runId });
    try { const r = await answerReport(runId); setReport({ runId, data: { title: r.title, markdown: r.markdown, tokens: r.input_tokens + r.output_tokens, ms: r.latency_ms } }); }
    catch (err: any) { setReport({ runId, error: err.message }); }
  };

  // bấm nguồn: mở đúng đoạn ở cột phải (điện thoại: ngăn kéo), tô từ khóa của câu hỏi; quyền kiểm ở máy chủ như trước
  const showChunk = async (id: string) => {
    const sourceId = id.replace(/_c\d+$/, '');
    setChunk({ id, sourceId }); setCtxTab('sources'); setCtxOpen(true); foldCtx(false);
    try { const c = await getChunk(id); setChunk({ id, sourceId, source: c.source_name, text: c.text }); }
    catch (err: any) { setChunk({ id, sourceId, error: err.message }); }
  };
  const saveAnswer = async (runId: string, question: string, markdown: string, cites: string[]) => {
    setSaved(s => ({ ...s, [runId]: 'Đang lưu…' }));
    try { await saveReport({ kind: 'answer', title: question.slice(0, 160) || 'Câu trả lời', workspace_id: workspaceId ? String(workspaceId) : null, payload: { run_id: runId, question, markdown, citations: cites, sources: cites.map(c => citeLabel(c, docsForCite)) } }); setSaved(s => ({ ...s, [runId]: 'Đã lưu vào Kết quả' })); }
    catch (err: any) { setSaved(s => ({ ...s, [runId]: err.message })); }
  };
  const wordOf = async (runId: string, question: string, markdown: string) => {
    try { saveBlob(`tra-loi_${runId.slice(-8)}.docx`, await exportDocx(`# ${question}\n\n${markdown}`)); }
    catch (err: any) { setError(`Không xuất được Word: ${err.message}`); }
  };

  const myCards = cards.filter(c => c.convo === (conversationId ?? ''));
  const fresh = messages.length === 0 && !pending && myCards.length === 0 && !clarify;
  const docsForCite = allDocs.length ? allDocs : docs;
  const cardsAt = (i: number) => myCards.filter(c => (i < 0 ? c.after >= messages.length : c.after === i)).map(c => (
    <React.Fragment key={`card-${c.id}`}>
      <div className="ws-msg is-user"><p>{c.question}</p></div>
      <div className="ws-msg is-bot is-card">
        {c.out ? <SkillCard label={c.label} reason={c.reason} out={c.out} citeLabel={id => citeLabel(id, docsForCite)} onCite={showChunk} />
          : c.error ? <p className="note is-error" role="alert">Kỹ năng {c.label} chưa chạy được: {c.error}</p>
          : null}
      </div>
    </React.Fragment>));
  const slashQ = !forced && draft.startsWith('/') ? draft.slice(1).trim().toLowerCase() : null;
  const slashHits = slashQ === null ? [] : SKILL_LIST.filter(k => !slashQ || k.label.toLowerCase().includes(slashQ));
  // kỹ năng cần bảng hoặc danh mục tiêu chí riêng: "/" mở thẳng kỹ năng đó trong danh mục (Đợt 5)
  const TOOL_LINKS = [
    { label: 'Rà soát theo tiêu chí', hint: 'Kiểm tài liệu theo danh mục tiêu chí: Có, Chưa rõ, Chưa thấy, kèm nguồn', pack: 'general', id: 'criteria' },
    { label: 'Bảng dữ liệu theo quy định', hint: 'Tải bảng Excel, máy so từng dòng với ngưỡng trong quy chế', pack: 'education', id: 'roster' },
    { label: 'Danh mục kỹ năng', hint: 'Mọi kỹ năng theo ngành: giáo dục, công ty, văn phòng, kỹ thuật', pack: '', id: '' },
  ];
  const toolHits = slashQ === null || !onOpenToolkit ? [] : TOOL_LINKS.filter(t => !slashQ || t.label.toLowerCase().includes(slashQ));
  const toolkitHit = toolHits.length > 0;
  const openTool = (t: typeof TOOL_LINKS[number]) => { setDraft(''); if (t.id) window.dispatchEvent(new CustomEvent('oq-open-tool', { detail: { pack: t.pack, id: t.id } })); else onOpenToolkit!(); };
  const pickSlash = (k: SkillKey) => { setForced(k); setDraft(''); inputRef.current?.focus(); };
  const busyNow = busy(state) || !!pending;

  const composer = (
    <form ref={formRef} className={`ws-composer${open || !fresh ? ' is-open' : ''}${pending ? ' is-busy' : ''}`} onSubmit={send} onClick={expand}>
      {!(open || !fresh) ? (
        <button type="button" className="ws-launch" aria-label="Mở khung hỏi đáp">
          <Sparkles size={16} /><span>Hỏi C27 về tài liệu của bạn…</span>
        </button>
      ) : <>
        {listening && <div className="ws-only is-live"><Mic size={13} /><span>Đang nghe… nói câu hỏi rồi dừng lại. Giọng nói do trình duyệt nhận dạng.</span><button type="button" onClick={() => recRef.current?.stop()}>Xong</button></div>}
        {only && <div className="ws-only"><FileText size={13} /><span>Chỉ hỏi trong <b>{only.name}</b></span><button type="button" onClick={() => setOnly(null)} aria-label="Bỏ giới hạn tài liệu">Hỏi cả kho</button></div>}
        {(slashHits.length > 0 || toolkitHit) && <div className="ws-slash" role="listbox" aria-label="Chọn kỹ năng">
          {slashHits.map((k, i) => <button key={k.key} type="button" role="option" aria-selected={i === 0} className={i === 0 ? 'is-on' : ''} onClick={() => pickSlash(k.key)}>
            <Sparkles size={16} /><b>{k.label}</b><small>{k.hint}</small></button>)}
          {toolHits.map((t, i) => <button key={t.label} type="button" role="option" aria-selected={slashHits.length === 0 && i === 0} className={slashHits.length === 0 && i === 0 ? 'is-on' : ''} onClick={() => openTool(t)}>
            <Wrench size={16} /><b>{t.label}</b><small>{t.hint}</small></button>)}
        </div>}
        {forced && <div className="ws-only"><Sparkles size={13} /><span>Kỹ năng: <b>{SKILL_LIST.find(k => k.key === forced)?.label}</b></span><button type="button" onClick={() => setForced(null)}>Bỏ chọn</button></div>}
        {image && <div className="ws-img"><img src={image.url} alt="Ảnh đính kèm" /><span>Ảnh đính kèm · chữ trong ảnh sẽ được đọc khi gửi</span>
          <button type="button" onClick={() => { URL.revokeObjectURL(image.url); setImage(null); }} aria-label="Bỏ ảnh đính kèm"><X size={14} /></button></div>}
        <textarea ref={inputRef} rows={fresh ? 3 : 1} value={draft} aria-label="Câu hỏi hoặc yêu cầu"
          onPaste={e => {
            const item = Array.from(e.clipboardData?.items ?? []).find(it => it.type.startsWith('image/'));
            const f = item?.getAsFile(); if (!f) return;
            e.preventDefault();
            setPasting(true);
            toPng(f).then(b => setImage({ blob: b, url: URL.createObjectURL(b) })).catch((err: Error) => setError(err.message)).finally(() => setPasting(false));
          }}
          placeholder={mode === 'quick' ? (forced ? 'Mô tả trường hợp hoặc yêu cầu cho kỹ năng…' : 'Hỏi bất kỳ điều gì, dán ảnh (Ctrl+V), hoặc gõ "/" để chọn kỹ năng…') : 'Mô tả yêu cầu cần phân tích…'}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (slashHits.length) pickSlash(slashHits[0].key); else if (toolkitHit) openTool(toolHits[0]); else void send(); }
            else if (e.key === 'Escape' && slashHits.length) setDraft('');
          }} />
        <div className="ws-bar">
          {/* Tự động: hệ thống tự chọn trả lời thẳng / kỹ năng / nhiều tác tử. A/B/C chỉ còn ở trang Thực nghiệm (đợt 4, đã duyệt 19/11). */}
          {onUploadFile && <button type="button" className="ws-mic ws-attach" onClick={() => fileRef.current?.click()} aria-label="Đính kèm tài liệu" title="Tải tài liệu lên kho của không gian này"><Paperclip size={17} /></button>}
          <button type="button" className="ws-skillbtn" onClick={() => { setForced(null); setDraft('/'); inputRef.current?.focus(); }} aria-label="Chọn kỹ năng" title="Chọn kỹ năng (hoặc gõ /)"><Sparkles size={14} />Kỹ năng</button>
          <span className="ws-auto" title={MODE_INFO.quick.hint}>Tự động</span>
          {Recognition && <button type="button" className={`ws-mic${listening ? ' is-on' : ''}`} onClick={listen} disabled={!!pending} aria-pressed={listening}
            aria-label={listening ? 'Dừng nghe' : 'Hỏi bằng giọng nói'} title="Nói thay vì gõ (tiếng Việt). Trình duyệt nhận dạng giọng nói; Chrome và Edge có thể gửi âm thanh lên máy chủ của họ để nhận dạng."><Mic size={17} /></button>}
          <button type="submit" className="send" disabled={!!pending || pasting || (!draft.trim() && !image)} aria-label="Gửi">{pending ? <span className="spin" /> : <ArrowUp size={18} />}</button>
        </div>
      </>}
    </form>
  );

  const lastRunId = [...messages].reverse().find(m => m.run_id && runs[m.run_id!])?.run_id;
  const ctxRun = runs[focusRun ?? lastRunId ?? ''];
  // câu hỏi của lượt đang xem (để tô từ khóa trong trích dẫn): lấy từ hội thoại, kể cả hội thoại cũ vừa mở lại
  const ctxAt = messages.findIndex(m => m.run_id && m.run_id === (focusRun ?? lastRunId));
  const ctxAsk = (ctxAt > 0 ? [...messages.slice(0, ctxAt)].reverse().find(m => m.role === 'USER')?.content : undefined) ?? lastAsk;
  return (
    <div className={`ws-shell ws-v2${ctxFold ? ' is-folded' : ''}${officeSrc && officeMode === 'open' ? ' has-office' : ''}`}>
    <main className={`mn ws${fresh ? ' is-fresh' : ''}`}>
      <div className="ws-top">
        <div className={`ws-bot${busyNow ? ' is-busy' : ''}`} aria-label="Chạm vào Trợ lý C27" title="Chạm để C27 phản hồi">
          <AssistantRobot size={fresh ? 132 : 44} interactive colorConfig={{ shell: '#1d344a', trim: '#d5dde6', screen: state === 'error' ? '#ff8a8a' : busyNow ? '#ffd27a' : '#8fdcff' }} />
        </div>
        <p className="ws-say" aria-live="polite"><span className="sr">{speechText}</span><span aria-hidden="true">{typed}<i className="ws-caret" /></span></p>
        <button type="button" className="icon-btn is-sm ws-ctx-btn" onClick={() => setCtxOpen(true)} aria-label="Mở nguồn và quá trình xử lý" title="Nguồn và quá trình xử lý"><PanelRight size={15} /></button>
      </div>

      {fresh ? (
        <div className="ws-hero">
          <div className="ws-glow" aria-hidden="true"><i /><i /><i /></div>
          <h1>Chào {firstName(userName) || 'bạn'}, <span>cần tìm gì hôm nay?</span></h1>
          {/* bỏ dòng tình trạng kho ở khung giữa (24/11, chủ dự án duyệt) */}
          {composer}
          <div className={`ws-chips${open ? ' is-in' : ''}`}>
            {PRESETS.map(p => <button key={p.label} type="button" onClick={() => { setOpen(true); setDraft(p.text); setMode('quick'); inputRef.current?.focus(); speak('Đã điền câu hỏi. Bạn sửa thêm hoặc nhấn gửi nhé.'); }}>{p.label}</button>)}
          </div>
          {open && suggested.length > 0 && <div className="ws-suggest"><p>Gợi ý từ hồ sơ tài liệu</p><div>
            {suggested.map(s => <button key={s.question} type="button" title={s.source} onClick={() => { setMode('quick'); setDraft(s.question); inputRef.current?.focus(); }}>{s.question}</button>)}
          </div></div>}
          {docCount === 0 && onUploadFile && <div className="ws-start" aria-label="Bắt đầu với tài liệu">
            <button type="button" className="ws-start-up" onClick={() => fileRef.current?.click()}><Upload size={16} />Tải tài liệu của bạn lên</button>
          </div>}
          {recent.length > 0 && <div className="ws-recent">
            <p>Tiếp tục</p>
            {/* cùng một câu hỏi hỏi nhiều lần chỉ hiện cuộc trò chuyện mới nhất */}
            {recent.filter((c, i, all) => all.findIndex(x => (x.title || '') === (c.title || '')) === i).slice(0, 3).map(c => (
              <button key={c.conversation_id} type="button" onClick={() => onConversation(c.conversation_id)}>
                <MessageSquareText size={15} /><span>{c.title || 'Không tên'}</span><small>{ago(c.updated_at)}</small><ArrowRight size={14} />
              </button>
            ))}
          </div>}
          {error && <p className="note is-error" role="alert">{error}</p>}
        </div>
      ) : (
        <div className="ws-thread">
          <div className="ws-msgs">
            {messages.flatMap((m, i) => [...cardsAt(i), ((): React.ReactNode => {
              if (m.role === 'USER') {
                const prev = messages[i - 1], asked = messages[i - 2];
                // Câu hỏi được gửi lại tự động sau lượt Phân tích bị từ chối: thay bằng một dòng ghi chú.
                if (prev?.run_id && isPlanRejected(runs[prev.run_id]) && asked?.role === 'USER' && asked.content === m.content)
                  return <p key={m.message_id} className="note ws-fallback">Đã tự trả lời lại bằng chế độ Tự động.</p>;
                const { ask, ocr } = splitAsk(m.content);
                return <div key={m.message_id} className="ws-msg is-user"><p>{ask}</p>
                  {ocr && <details className="ws-ocr"><summary>Ảnh đính kèm · chữ nhận dạng được</summary><p>{ocr}</p></details>}
                  <button type="button" className="ws-edit" onClick={() => { setDraft(ask); setOpen(true); inputRef.current?.focus(); }} aria-label="Sửa câu hỏi này rồi gửi lại" title="Sửa rồi gửi lại"><Pencil size={13} /></button></div>;
              }
              const stored = parseSkillMessage(m.content);
              if (stored) return (
                <div key={m.message_id} className="ws-msg is-bot is-card">
                  <SkillCard label={stored.card.label} reason={stored.card.reason} out={{ skill: stored.card.skill, data: stored.card.data } as SkillOutput}
                    citeLabel={id => citeLabel(id, docsForCite)} onCite={showChunk} />
                </div>);
              const run = m.run_id ? runs[m.run_id] : undefined;
              const quick = isQuick(run);
              const cites = citationsOf(run);
              const failed = run?.status === 'FAILED';
              // "Theo tác tử": lượt có nhiều nhiệm vụ hoặc có tác tử chuyên môn (kể cả ô chat Tự động)
              const hasAgents = (run?.task_results?.length ?? 0) > 1 || (!quick && (run?.task_results?.length ?? 0) > 0) || !!run?.task_results?.some((r: any) => r.domain && r.domain !== 'general');
              const result = run ? adaptRun(run) : null;
              return (
                <article key={m.message_id} className="ws-msg is-bot">
                  <header>
                    <span className="ws-tag">{quick ? <><Sparkles size={12} />Tự động</> : <><Microscope size={12} />{CONDITION_LABEL[run?.condition] ?? 'Phân tích'}</>}</span>
                    {run?.status && <span className={`cht-status is-${String(run.status).toLowerCase()}`}>{STATUS_LABEL[run.status] ?? run.status}</span>}
                    {(() => { const fu = run?.events?.find((e: any) => e.stage === 'follow_up_resolved'); return fu ? <span className="ws-fu" title="Câu hỏi ngắn được hiểu theo câu hỏi trước trong cuộc trò chuyện (chỉ để hiểu ý, không phải nguồn)"><CornerDownRight size={12} />Hiểu tiếp theo: “{String(fu.previous_request).slice(0, 70)}”</span> : null; })()}
                  </header>
                  <div className="md"><Markdown text={failed ? explainFailure(m.content) : inlineCites(stripSources(answerText(m.content)), allDocs.length ? allDocs : docs)} /></div>
                  {cites.length > 0 && <SourceList cites={cites} docs={allDocs.length ? allDocs : docs} onCite={showChunk} />}
                  {run && <footer>
                    <span className="ws-meta">{((run.metrics?.input_tokens ?? 0) + (run.metrics?.output_tokens ?? 0)).toLocaleString('vi-VN')} token · {((run.metrics?.latency_ms ?? 0) / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây</span>
                    <button type="button" onClick={() => { setFocusRun(run.run_id); setCtxTab('process'); setCtxOpen(true); }}><ListChecks size={13} />Quá trình</button>
                    <button type="button" onClick={() => result && setTrace({ result, step: PIPELINE_STEPS[0] })}><Footprints size={13} />8 bước</button>
                    {quick && Array.isArray(run.events) && run.events.length > 0 && <button type="button" onClick={() => setOffice({ kind: 'replay', question: splitAsk(String(run.query ?? '')).ask, events: run.events })} title="Diễn lại lượt này trong văn phòng 3D theo mốc thời gian đã lưu"><Bot size={13} />Văn phòng</button>}
                    {hasAgents && <button type="button" aria-expanded={agentsOf === run.run_id} onClick={() => setAgentsOf(agentsOf === run.run_id ? null : run.run_id)}><Users size={13} />Theo tác tử</button>}
                    {!failed && run.status !== 'NO_EVIDENCE' && <GroundingButton open={groundOf === run.run_id} onToggle={() => setGroundOf(groundOf === run.run_id ? null : run.run_id)} />}
                    {!failed && <button type="button" onClick={() => readAloud(run.run_id, m.content)} aria-pressed={speaking === run.run_id}
                      title={viVoice ? 'Đọc to câu trả lời' : 'Máy chưa cài giọng đọc tiếng Việt; trình duyệt sẽ đọc bằng giọng mặc định'}>{speaking === run.run_id ? <><Square size={12} />Dừng đọc</> : <><Volume2 size={13} />Đọc to</>}</button>}
                    {!failed && run.status !== 'NO_EVIDENCE' && <button type="button" onClick={() => openReport(run.run_id)} title="Viết thành báo cáo hoàn chỉnh, tải Word hoặc PDF"><FileDown size={13} />Báo cáo</button>}
                    {!failed && <AnswerFeedback key={run.run_id} runId={run.run_id} initial={ratings[run.run_id]} onSaved={r => setRatings(p => ({ ...p, [run.run_id]: r }))} />}
                  </footer>}
                  {run && quick && Array.isArray(run.events) && run.events.length > 0 && <RunTimeline groups={timelineOf(run.events)}
                    onSeek={ix => setOffice({ kind: 'replay', question: splitAsk(String(run.query ?? '')).ask, events: run.events, seek: ix })} />}
                  {run && !failed && run.status !== 'NO_EVIDENCE' && (() => {
                    const q = messages.slice(0, i).reverse().find(x => x.role === 'USER')?.content ?? '';
                    const md = stripSources(answerText(m.content));
                    return <div className="ws-next" aria-label="Bước tiếp theo"><span>Bước tiếp theo</span>
                      {canSaveReports() && <button type="button" onClick={() => saveAnswer(run.run_id, q, md, cites)} disabled={!!saved[run.run_id]}><Archive size={13} />{saved[run.run_id] ?? 'Lưu vào Kết quả'}</button>}
                      <button type="button" onClick={() => wordOf(run.run_id, q, md)}><FileDown size={13} />Xuất Word</button>
                      {cites.length > 0 && <button type="button" onClick={() => showChunk(cites[0])}><BookOpen size={13} />Mở nguồn</button>}
                      {quick && <span className="ws-reask"><button type="button" aria-expanded={reask === run.run_id} onClick={() => setReask(reask === run.run_id ? null : run.run_id)}><RotateCcw size={13} />Hiểu sai? Chọn lại</button>
                        {reask === run.run_id && <span className="ws-reask-menu" role="menu">{REASK.map(o => <button key={o.agent} role="menuitem" type="button" onClick={() => { setReask(null); void send(undefined, { text: q, agent: o.agent }); }}>{o.label}</button>)}</span>}</span>}
                    </div>;
                  })()}
                  {run && !failed && run.status !== 'NO_EVIDENCE' && groundOf === run.run_id && <GroundingPanel runId={run.run_id} cache={groundCache} setCache={setGroundCache} onShowChunk={showChunk} />}
                  {hasAgents && agentsOf === run!.run_id && <div className="ws-agents">
                    {result!.agent_results.map((a, i) => <section key={i}><h4>{a.agent_role.replace('Agent', '')} · {a.subtask_title}</h4><div className="md"><Markdown text={a.content} /></div></section>)}
                  </div>}
                </article>
              );
            })()])}
            {cardsAt(-1)}
            {clarify && !pending && <>
              <div className="ws-msg is-user"><p>{splitAsk(clarify.text).ask}</p></div>
              <div className="ws-msg is-bot ws-clarify" role="group" aria-label="Chọn cách hiểu câu hỏi">
                <p>{clarify.question}</p>
                <div>{clarify.options.map(o => <button key={o.agent} type="button" className="btn btn-dark is-sm" onClick={() => void send(undefined, { text: clarify.text, agent: o.agent })}>{o.label}</button>)}
                  <button type="button" className="btn btn-ghost is-sm" onClick={() => { setDraft(clarify.text); setClarify(null); inputRef.current?.focus(); }}>Sửa câu hỏi</button></div>
              </div>
            </>}
            {pending && <>
              <div className="ws-msg is-user">{pending.image && <img className="ws-msg-img" src={pending.image} alt="Ảnh đính kèm" />}<p>{splitAsk(pending.text).ask}</p></div>
              <div className="ws-msg is-bot is-wait is-live">
                {(() => {
                  const phase = phaseOf(live.steps, live.answer);
                  const note = live.answer ? 'Đang viết câu trả lời' : live.steps[live.steps.length - 1] ?? (pending.mode === 'quick' ? 'Đang tìm trong tài liệu' : 'Các tác tử đang làm việc');
                  return <section className="ws-proc" aria-label="Quá trình xử lý">
                    <div className="ws-proc-head"><b><Sparkles size={15} />Đang xử lý yêu cầu…</b><small>Đã xử lý {elapsed} giây</small>
                      {agentsLive && <button type="button" className="ws-proc-office" onClick={() => setOffice({ kind: 'live' })} title="Xem các Agent nhận việc và làm việc trong văn phòng 3D, theo sự kiện thật"><Bot size={13} />Xem văn phòng</button>}</div>
                    <ol className="ws-proc-steps">{PHASES.map((p, i) => (
                      <li key={p.t} className={i < phase ? 'is-done' : i === phase ? 'is-now' : ''} aria-current={i === phase ? 'step' : undefined}>
                        <span className="ws-proc-dot">{i < phase ? <Check size={13} /> : i === phase ? <span className="spin is-dark" /> : null}</span>
                        <span><b>{p.t}</b><small>{p.d}</small></span></li>))}</ol>
                    <p className="ws-proc-note" aria-live="polite"><Zap size={14} /><b>Cập nhật nhanh:</b><span>{note}</span></p>
                    {agentsLive && <RunTimeline live groups={buildTimeline(getLive()?.events ?? [])} onSeek={() => setOffice({ kind: 'live' })} />}
                  </section>;
                })()}
                {live.answer && <div className="md ws-live-answer"><Markdown text={inlineCites(stripSources(live.answer), allDocs.length ? allDocs : docs)} /></div>}
              </div>
            </>}
            <div ref={endRef} />
          </div>
          {error && <p className="note is-error ws-err" role="alert"><span>{error}</span>
            {lastAsk && !pending && <button type="button" className="btn btn-ghost is-sm" onClick={() => { setDraft(''); void send(undefined, undefined, lastAsk); }}><RotateCcw size={13} />Thử lại</button>}</p>}
          {composer}
        </div>
      )}

      {trace && <NodeTraceModal isOpen step={trace.step} result={trace.result} onClose={() => setTrace(null)} onSelectStep={s => setTrace({ ...trace, step: s })} docs={docsForCite} />}
      {report && <StudioModal labelId="ws-report" icon={<FileDown size={18} />} title={report.data?.title || 'Báo cáo từ câu trả lời'}
        subtitle={report.data ? `Mô hình cục bộ biên soạn · ${report.data.tokens.toLocaleString('vi-VN')} token · ${(report.data.ms / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} giây` : 'Viết thành báo cáo có cấu trúc từ câu trả lời và các đoạn tài liệu đã dùng'}
        onClose={() => setReport(null)}
        footer={<>{report.data && <ExportButtons title={report.data.title} markdown={report.data.markdown} filename={`bao-cao_${report.runId.slice(-8)}`} />}
          {(report.data || report.error) && <button className="btn btn-ghost" onClick={() => openReport(report.runId, true)}><RefreshCw size={14} />Viết lại</button>}
          <button className="btn btn-dark" onClick={() => setReport(null)}>Đóng</button></>}>
        {report.error ? <p className="note is-error">{report.error}</p> : !report.data ? <p className="muted-line"><span className="spin is-dark" />Đang viết báo cáo, thường mất 30–60 giây…</p>
          : <div className="md ws-report"><Markdown text={report.data.markdown} /></div>}
      </StudioModal>}
          <input ref={fileRef} type="file" hidden multiple accept=".pdf,.docx,.xlsx,.md,.markdown,.sql,.txt,.png,.jpg,.jpeg,.tif,.tiff"
            onChange={e => { const fs = Array.from(e.target.files ?? []); e.target.value = ''; setError(null);
              void (async () => { const bad: string[] = []; for (const f of fs) { try { await onUploadFile?.(f); } catch (err: any) { bad.push(`${f.name}: ${err.message}`); } }
                if (bad.length) setError(`Không thêm được ${bad.join('; ')}`); })(); }} />
      {fullDoc && <DocumentReader sourceId={fullDoc.id} sourceName={fullDoc.name} onClose={() => setFullDoc(null)} />}
    </main>
    <WorkspaceContext tab={ctxTab} onTab={setCtxTab} docs={docs} picked={picked} onPick={setPicked} chunk={chunk} question={ctxAsk} onCloseChunk={() => setChunk(null)}
      onOpenFull={(id, name) => setFullDoc({ id, name })} run={ctxRun} live={pending ? { steps: live.steps, elapsed } : null} draft={draft}
      onUseSkill={k => { setForced(k); setDraft(''); setOpen(true); setCtxOpen(false); inputRef.current?.focus(); }} manage={manage}
      mobileOpen={ctxOpen} onMobileClose={() => setCtxOpen(false)} collapsed={ctxFold} onCollapse={foldCtx}
      cites={citationsOf(ctxRun).map(id => ({ id, label: citeLabel(id, docsForCite) }))} onCite={showChunk} />
    <OfficePanel source={officeSrc} mode={officeMode} onMode={setOfficeMode} />
    </div>
  );
};
