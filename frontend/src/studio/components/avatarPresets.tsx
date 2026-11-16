// Bộ ảnh đại diện mẫu: tất cả tự vẽ (SVG), emoji hệ thống hoặc dải màu CSS, không dùng hình có bản quyền.
// Mã ảnh (id) được lưu ở backend dạng "preset:<id>", khớp ràng buộc [a-z0-9-]{1,32}. Không đổi hay xóa mã cũ
// (robot-c27, meo, cao, gau-truc, cu, ngoai-hanh-tinh, ma, xuong-rong, may, e-…) vì người dùng có thể đã chọn.
import React from 'react';

export interface Preset { id: string; label: string; node: React.ReactNode }
export interface PresetGroup { key: string; label: string; items: Preset[] }

const G = {
  sun: 'linear-gradient(135deg,#ffe259,#ffa751)', peach: 'linear-gradient(135deg,#ffd3a5,#fd6585)', rose: 'linear-gradient(135deg,#ffb2c1,#ff6f91)',
  berry: 'linear-gradient(135deg,#f093fb,#f5576c)', grape: 'linear-gradient(135deg,#c3a6ff,#7b5cff)', violet: 'linear-gradient(135deg,#8e78ff,#4b2fc9)',
  ocean: 'linear-gradient(135deg,#4facfe,#00c9fe)', sky: 'linear-gradient(135deg,#a1c4fd,#6fa8ff)', mint: 'linear-gradient(135deg,#84fab0,#5cc8f0)',
  lime: 'linear-gradient(135deg,#d4fc79,#5fd68a)', forest: 'linear-gradient(135deg,#43e97b,#1fb8a8)', night: 'linear-gradient(135deg,#2a5298,#1e2f5c)',
  ink: 'linear-gradient(135deg,#3a4150,#191d26)', sand: 'linear-gradient(135deg,#fff3e0,#e9c9a6)', flame: 'linear-gradient(135deg,#ff8a00,#ff3d3d)',
  aurora: 'linear-gradient(135deg,#00c6fb,#005bea)', ice: 'linear-gradient(135deg,#e0f2ff,#9fd3ff)', candy: 'linear-gradient(135deg,#ffecd2,#fcb69f)',
};
const CYCLE = Object.values(G);

const art = (bg: string, content?: React.ReactNode) => <span className="av-art" style={{ background: bg }}>{content}</span>;
const svg = (body: React.ReactNode) => <svg viewBox="0 0 64 64" aria-hidden="true">{body}</svg>;
const emo = (e: string) => <i className="av-emo">{e}</i>;
const emojiGroup = (rows: Array<[string, string, string]>, offset = 0): Preset[] =>
  rows.map(([id, e, label], i) => ({ id, label, node: art(CYCLE[(i * 5 + offset) % CYCLE.length], emo(e)) }));

// ---------- Nhân vật: ghép màu da, kiểu tóc, áo, kính ----------
type Hair = 'short' | 'long' | 'bun' | 'curly' | 'spiky' | 'beard' | 'scarf' | 'side';
function person(skin: string, hair: string, style: Hair, shirt: string, glasses = false) {
  const back = style === 'long' ? <path d="M17 31 C15 14 25 9 32 9 C40 9 49 14 47 31 L49 50 L15 50 Z" fill={hair} />
    : style === 'scarf' ? <path d="M16 34 C14 15 24 8 32 8 C40 8 50 15 48 34 C48 46 42 52 32 52 C22 52 16 46 16 34 Z" fill={hair} /> : null;
  const top = {
    short: <path d="M19 27 C18 14 26 10 33 10 C41 10 46 15 45 27 C43 20 38 17 32 17 C26 17 22 20 19 27 Z" fill={hair} />,
    long: <path d="M20 25 C21 15 29 12 34 12 C41 12 45 18 44 26 C37 19 28 19 20 25 Z" fill={hair} />,
    bun: <><circle cx="32" cy="9" r="6" fill={hair} /><path d="M20 26 C19 15 26 12 32 12 C39 12 45 15 44 26 C41 19 37 17 32 17 C27 17 23 19 20 26 Z" fill={hair} /></>,
    curly: <>{[[20, 22], [24, 15], [31, 12], [38, 14], [43, 21], [27, 18], [36, 18]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r="6" fill={hair} />)}</>,
    spiky: <path d="M19 27 L18 16 L23 19 L24 10 L29 16 L32 8 L35 16 L40 10 L41 19 L46 16 L45 27 C42 20 37 18 32 18 C27 18 22 20 19 27 Z" fill={hair} />,
    beard: <><path d="M21 31 C22 43 27 46 32 46 C37 46 42 43 43 31 C40 37 36 38 32 38 C28 38 24 37 21 31 Z" fill={hair} /><path d="M21 22 C22 15 27 13 32 13 C37 13 42 15 43 22 C39 18 25 18 21 22 Z" fill={hair} /></>,
    scarf: null,
    side: <path d="M19 28 C17 14 27 10 34 10 C42 10 47 16 45 26 C41 19 33 17 24 22 C22 23 20 25 19 28 Z" fill={hair} />,
  }[style];
  return svg(<>
    {back}
    <path d="M9 64 C11 50 21 45 32 45 C43 45 53 50 55 64 Z" fill={shirt} />
    <path d="M26 45 L32 52 L38 45 Z" fill="rgba(255,255,255,.35)" />
    <rect x="27.5" y="36" width="9" height="10" rx="3" fill={skin} /><rect x="27.5" y="38" width="9" height="3" fill="rgba(0,0,0,.08)" />
    {style !== 'scarf' && <><circle cx="20" cy="29" r="3" fill={skin} /><circle cx="44" cy="29" r="3" fill={skin} /></>}
    <ellipse cx="32" cy="28" rx={style === 'scarf' ? 10.5 : 12} ry={style === 'scarf' ? 12 : 13} fill={skin} />
    {top}
    <circle cx="27" cy="29" r="1.9" fill="#1f2937" /><circle cx="37" cy="29" r="1.9" fill="#1f2937" />
    <circle cx="27.6" cy="28.4" r=".6" fill="#fff" /><circle cx="37.6" cy="28.4" r=".6" fill="#fff" />
    <circle cx="23.5" cy="33.5" r="2.4" fill="#ff7a9a" opacity=".35" /><circle cx="40.5" cy="33.5" r="2.4" fill="#ff7a9a" opacity=".35" />
    {style !== 'beard' && <path d="M28 35 Q32 38.6 36 35" stroke="#7a2e2e" strokeWidth="1.7" fill="none" strokeLinecap="round" />}
    {glasses && <g stroke="#1f2937" strokeWidth="1.4" fill="rgba(255,255,255,.18)"><circle cx="27" cy="29" r="4.6" /><circle cx="37" cy="29" r="4.6" /><path d="M31.6 29 H32.4" /></g>}
  </>);
}
const PEOPLE: Preset[] = ([
  ['nv-an', 'Bạn tóc ngắn', '#f6d2b8', '#2d1b12', 'short', '#2563eb', false, G.sky],
  ['nv-mai', 'Bạn tóc dài', '#ffdcc2', '#3b2414', 'long', '#ec4899', false, G.rose],
  ['nv-linh', 'Bạn búi tóc', '#f1c9a5', '#111827', 'bun', '#10b981', true, G.mint],
  ['nv-khoa', 'Bạn tóc xoăn', '#c68642', '#1b1b1b', 'curly', '#f59e0b', false, G.sun],
  ['nv-duy', 'Bạn tóc dựng', '#f9d7c0', '#c2410c', 'spiky', '#7c3aed', false, G.grape],
  ['nv-hung', 'Bác râu', '#e8b896', '#6b7280', 'beard', '#0f766e', true, G.forest],
  ['nv-nour', 'Bạn khăn trùm', '#d9a77c', '#6d28d9', 'scarf', '#f97316', false, G.peach],
  ['nv-tuan', 'Bạn rẽ ngôi', '#8d5524', '#0b0b0b', 'side', '#1e40af', true, G.aurora],
  ['nv-ha', 'Bạn tóc vàng', '#ffe0c7', '#e0b04a', 'long', '#14b8a6', true, G.ice],
  ['nv-phong', 'Bạn tóc nâu', '#f1c27d', '#6b3e26', 'short', '#dc2626', true, G.candy],
  ['nv-thao', 'Bạn tóc tím', '#ffd8c4', '#8b5cf6', 'bun', '#0ea5e9', false, G.berry],
  ['nv-kai', 'Bạn tóc trắng', '#a86b3c', '#e5e7eb', 'curly', '#111827', false, G.night],
] as const).map(([id, label, skin, hair, style, shirt, glasses, bg]) => ({ id, label, node: art(bg, person(skin, hair, style, shirt, glasses)) }));

// ---------- Robot: biến thể của Robot C27 ----------
type Eyes = 'sq' | 'round' | 'happy' | 'heart' | 'visor' | 'wink';
function robot(body: string, screen: string, eye: string, tip: string, eyes: Eyes) {
  const e = {
    sq: <><rect x="22" y="28" width="6" height="8" rx="1.5" fill={eye} /><rect x="36" y="28" width="6" height="8" rx="1.5" fill={eye} /></>,
    round: <><circle cx="25" cy="32" r="4" fill={eye} /><circle cx="39" cy="32" r="4" fill={eye} /></>,
    happy: <g stroke={eye} strokeWidth="2.6" fill="none" strokeLinecap="round"><path d="M21 34 Q25 28 29 34" /><path d="M35 34 Q39 28 43 34" /></g>,
    heart: <g fill={eye}><path d="M25 37 L20.5 32.5 A2.6 2.6 0 0 1 25 29 A2.6 2.6 0 0 1 29.5 32.5 Z" /><path d="M39 37 L34.5 32.5 A2.6 2.6 0 0 1 39 29 A2.6 2.6 0 0 1 43.5 32.5 Z" /></g>,
    visor: <rect x="20" y="29" width="24" height="6" rx="3" fill={eye} />,
    wink: <><rect x="22" y="28" width="6" height="8" rx="1.5" fill={eye} /><path d="M35 33 H43" stroke={eye} strokeWidth="2.6" strokeLinecap="round" /></>,
  }[eyes];
  return svg(<>
    <line x1="32" y1="9" x2="32" y2="17" stroke={body} strokeWidth="2.5" /><circle cx="32" cy="8" r="4" fill={tip} /><circle cx="30.8" cy="6.8" r="1.2" fill="#fff" opacity=".7" />
    <rect x="7" y="27" width="5" height="12" rx="2.5" fill="#cbd5e1" /><rect x="52" y="27" width="5" height="12" rx="2.5" fill="#cbd5e1" />
    <rect x="12" y="17" width="40" height="32" rx="11" fill={body} /><rect x="12" y="17" width="40" height="12" rx="11" fill="rgba(255,255,255,.14)" />
    <rect x="17" y="22" width="30" height="22" rx="7" fill={screen} />{e}
    <path d="M24 55 H40" stroke={body} strokeWidth="5" strokeLinecap="round" />
  </>);
}
const ROBOTS: Preset[] = [
  { id: 'robot-c27', label: 'Robot C27', node: art(G.sky, robot('#1d3557', '#0b1626', '#7fd3ff', '#f472b6', 'sq')) },
  { id: 'rb-vui', label: 'Robot vui vẻ', node: art(G.sun, robot('#1d3557', '#0b1626', '#ffd166', '#ff6b6b', 'happy')) },
  { id: 'rb-tim', label: 'Robot đáng yêu', node: art(G.rose, robot('#be185d', '#3b0a24', '#ff9ac1', '#ffd6e7', 'heart')) },
  { id: 'rb-xanh', label: 'Robot xanh lá', node: art(G.lime, robot('#166534', '#052e16', '#86efac', '#facc15', 'round')) },
  { id: 'rb-tim-tim', label: 'Robot tím', node: art(G.grape, robot('#4c1d95', '#1e0b47', '#c4b5fd', '#22d3ee', 'visor')) },
  { id: 'rb-cam', label: 'Robot cam', node: art(G.candy, robot('#c2410c', '#431407', '#fdba74', '#38bdf8', 'wink')) },
  { id: 'rb-dem', label: 'Robot ban đêm', node: art(G.night, robot('#e2e8f0', '#0f172a', '#38bdf8', '#f472b6', 'round')) },
  { id: 'rb-bac', label: 'Robot bạc', node: art(G.ink, robot('#94a3b8', '#111827', '#4ade80', '#fb7185', 'sq')) },
  { id: 'ngoai-hanh-tinh', label: 'Người ngoài hành tinh', node: art(G.mint, svg(<>
    <line x1="22" y1="16" x2="18" y2="7" stroke="#16a34a" strokeWidth="2" /><line x1="42" y1="16" x2="46" y2="7" stroke="#16a34a" strokeWidth="2" />
    <circle cx="18" cy="7" r="3" fill="#bbf7d0" /><circle cx="46" cy="7" r="3" fill="#bbf7d0" /><path d="M32 14 C50 14 54 30 46 44 C42 52 22 52 18 44 C10 30 14 14 32 14 Z" fill="#4ade80" />
    <ellipse cx="24" cy="32" rx="5" ry="7" fill="#052e16" transform="rotate(-25 24 32)" /><ellipse cx="40" cy="32" rx="5" ry="7" fill="#052e16" transform="rotate(25 40 32)" />
    <circle cx="23" cy="29" r="1.4" fill="#fff" /><circle cx="39" cy="29" r="1.4" fill="#fff" />
    <path d="M27 44 Q32 47 37 44" stroke="#052e16" strokeWidth="2" fill="none" strokeLinecap="round" /></>)) },
  { id: 'ma', label: 'Bóng ma vui', node: art(G.violet, svg(<>
    <path d="M16 54 V30 C16 18 24 12 32 12 C40 12 48 18 48 30 V54 L43 49 L38 54 L32 49 L26 54 L21 49 Z" fill="#fff" />
    <ellipse cx="26" cy="30" rx="3" ry="4.5" fill="#312e81" /><ellipse cx="38" cy="30" rx="3" ry="4.5" fill="#312e81" /><ellipse cx="32" cy="40" rx="3.5" ry="4" fill="#312e81" />
    <circle cx="20" cy="36" r="3" fill="#fbcfe8" /><circle cx="44" cy="36" r="3" fill="#fbcfe8" /></>)) },
];

// ---------- Động vật ----------
const ANIMALS: Preset[] = [
  { id: 'meo', label: 'Mèo cam', node: art(G.candy, svg(<>
    <path d="M14 26 L18 10 L28 20 Z M50 26 L46 10 L36 20 Z" fill="#f97316" /><path d="M17 22 L19 14 L24 19 Z M47 22 L45 14 L40 19 Z" fill="#fecaca" />
    <circle cx="32" cy="35" r="19" fill="#fb923c" /><ellipse cx="32" cy="41" rx="10" ry="7" fill="#fff7ed" />
    <ellipse cx="25" cy="33" rx="2.6" ry="3.6" fill="#1f2937" /><ellipse cx="39" cy="33" rx="2.6" ry="3.6" fill="#1f2937" />
    <path d="M29 39 L35 39 L32 42 Z" fill="#be185d" /><path d="M16 40 H8 M16 44 H9 M48 40 H56 M48 44 H55" stroke="#7c2d12" strokeWidth="1.4" strokeLinecap="round" /></>)) },
  { id: 'cao', label: 'Cáo nhỏ', node: art(G.sun, svg(<>
    <path d="M12 14 L26 24 L20 34 Z M52 14 L38 24 L44 34 Z" fill="#c2410c" /><path d="M12 24 Q32 8 52 24 L32 54 Z" fill="#f97316" />
    <path d="M20 34 Q32 30 44 34 L32 54 Z" fill="#fff7ed" /><circle cx="25" cy="31" r="2.6" fill="#1f2937" /><circle cx="39" cy="31" r="2.6" fill="#1f2937" />
    <circle cx="32" cy="50" r="3" fill="#1f2937" /></>)) },
  { id: 'gau-truc', label: 'Gấu trúc', node: art(G.lime, svg(<>
    <circle cx="16" cy="18" r="7" fill="#1f2937" /><circle cx="48" cy="18" r="7" fill="#1f2937" /><circle cx="32" cy="35" r="20" fill="#fff" />
    <ellipse cx="24" cy="33" rx="5" ry="6.5" fill="#1f2937" transform="rotate(-20 24 33)" /><ellipse cx="40" cy="33" rx="5" ry="6.5" fill="#1f2937" transform="rotate(20 40 33)" />
    <circle cx="24.5" cy="32" r="1.8" fill="#fff" /><circle cx="39.5" cy="32" r="1.8" fill="#fff" /><ellipse cx="32" cy="42" rx="3.2" ry="2.2" fill="#1f2937" /></>)) },
  { id: 'cu', label: 'Cú mèo', node: art(G.grape, svg(<>
    <path d="M16 18 L22 26 L14 28 Z M48 18 L42 26 L50 28 Z" fill="#4c1d95" /><ellipse cx="32" cy="38" rx="19" ry="20" fill="#8b5cf6" />
    <ellipse cx="32" cy="46" rx="11" ry="10" fill="#c4b5fd" />
    <circle cx="24" cy="32" r="8" fill="#fff" /><circle cx="40" cy="32" r="8" fill="#fff" /><circle cx="24" cy="32" r="3.6" fill="#1f2937" /><circle cx="40" cy="32" r="3.6" fill="#1f2937" />
    <path d="M29 40 L35 40 L32 45 Z" fill="#f59e0b" /></>)) },
  ...emojiGroup([
    ['e-cho', '🐶', 'Chó con'], ['e-ech', '🐸', 'Ếch'], ['e-ky-lan', '🦄', 'Kỳ lân'], ['e-cu-meo', '🦉', 'Cú'],
    ['dv-su-tu', '🦁', 'Sư tử'], ['dv-ho', '🐯', 'Hổ'], ['dv-tho', '🐰', 'Thỏ'], ['dv-chim-canh-cut', '🐧', 'Chim cánh cụt'],
    ['dv-gau-koala', '🐨', 'Gấu koala'], ['dv-bach-tuoc', '🐙', 'Bạch tuộc'], ['dv-ca-voi', '🐳', 'Cá voi'], ['dv-buom', '🦋', 'Bướm'],
    ['dv-hamster', '🐹', 'Chuột hamster'], ['dv-rua', '🐢', 'Rùa'], ['dv-khung-long', '🦖', 'Khủng long'], ['dv-ong', '🐝', 'Ong'],
  ], 2),
];

const FACES = emojiGroup([
  ['e-cuoi', '😄', 'Cười'], ['e-ngau', '😎', 'Ngầu'], ['e-nghi', '🤔', 'Suy nghĩ'], ['e-tim', '🥰', 'Đáng yêu'],
  ['bc-sao', '🤩', 'Phấn khích'], ['bc-thien-than', '😇', 'Thiên thần'], ['bc-tiec', '🥳', 'Tiệc tùng'], ['bc-ngu', '😴', 'Buồn ngủ'],
  ['bc-mot-sach', '🤓', 'Mọt sách'], ['bc-tinh-nghich', '😜', 'Tinh nghịch'], ['bc-cao-boi', '🤠', 'Cao bồi'], ['bc-lon-nguoc', '🙃', 'Lộn ngược'],
  ['bc-meo-cuoi', '😺', 'Mèo cười'], ['bc-ngoi-sao', '🌟', 'Ngôi sao'], ['bc-lua', '🔥', 'Bùng cháy'], ['bc-tim', '💖', 'Trái tim'],
], 0);

const FOOD = emojiGroup([
  ['e-cafe', '☕', 'Cà phê'], ['da-pizza', '🍕', 'Pizza'], ['da-donut', '🍩', 'Bánh donut'], ['da-sushi', '🍣', 'Sushi'],
  ['da-mi', '🍜', 'Mì'], ['da-tra-sua', '🧋', 'Trà sữa'], ['da-dau', '🍓', 'Dâu tây'], ['da-bo', '🥑', 'Bơ'],
  ['da-dua-hau', '🍉', 'Dưa hấu'], ['da-kem', '🍦', 'Kem'], ['da-burger', '🍔', 'Hamburger'], ['da-cupcake', '🧁', 'Bánh cupcake'],
  ['da-banh-quy', '🍪', 'Bánh quy'], ['da-chuoi', '🍌', 'Chuối'], ['da-dao', '🍑', 'Đào'], ['da-banh-mi', '🥖', 'Bánh mì'],
], 1);

const NATURE: Preset[] = [
  { id: 'xuong-rong', label: 'Xương rồng', node: art(G.rose, svg(<>
    <rect x="25" y="14" width="14" height="36" rx="7" fill="#22c55e" /><path d="M25 36 H18 a5 5 0 0 1 -5 -5 V24" stroke="#22c55e" strokeWidth="7" fill="none" strokeLinecap="round" />
    <path d="M39 30 H45 a5 5 0 0 0 5 -5 V20" stroke="#22c55e" strokeWidth="7" fill="none" strokeLinecap="round" /><circle cx="32" cy="13" r="4" fill="#f472b6" />
    <path d="M18 48 H46 L42 58 H22 Z" fill="#c2410c" /><circle cx="29" cy="28" r="1.6" fill="#14532d" /><circle cx="35" cy="28" r="1.6" fill="#14532d" />
    <path d="M29.5 33 Q32 35 34.5 33" stroke="#14532d" strokeWidth="1.5" fill="none" strokeLinecap="round" /></>)) },
  { id: 'may', label: 'Mây nhỏ', node: art(G.ocean, svg(<>
    <path d="M18 44 a9 9 0 0 1 1 -18 a13 13 0 0 1 25 -3 a10 10 0 0 1 2 21 Z" fill="#fff" />
    <circle cx="27" cy="33" r="2.4" fill="#0c4a6e" /><circle cx="38" cy="33" r="2.4" fill="#0c4a6e" />
    <path d="M29 38 Q32.5 41 36 38" stroke="#0c4a6e" strokeWidth="1.8" fill="none" strokeLinecap="round" />
    <path d="M24 50 l-2 5 M32 50 l-2 5 M40 50 l-2 5" stroke="#e0f2fe" strokeWidth="2" strokeLinecap="round" /></>)) },
  ...emojiGroup([
    ['e-hoa', '🌻', 'Hướng dương'], ['tn-cau-vong', '🌈', 'Cầu vồng'], ['tn-trang', '🌙', 'Trăng'], ['tn-mat-troi', '☀️', 'Mặt trời'],
    ['tn-bong-tuyet', '❄️', 'Bông tuyết'], ['tn-song', '🌊', 'Sóng biển'], ['tn-hoa-anh-dao', '🌸', 'Hoa anh đào'], ['tn-co-bon-la', '🍀', 'Cỏ bốn lá'],
    ['tn-trai-dat', '🌍', 'Trái đất'], ['tn-sao-tho', '🪐', 'Sao Thổ'], ['tn-la-phong', '🍁', 'Lá phong'], ['tn-nui-lua', '🌋', 'Núi lửa'],
    ['tn-xuong-rong-e', '🌵', 'Sa mạc'], ['tn-nam', '🍄', 'Nấm'],
  ], 3),
];

const HOBBY = emojiGroup([
  ['e-sach', '📚', 'Sách'], ['e-ten-lua', '🚀', 'Tên lửa'], ['st-game', '🎮', 'Chơi game'], ['st-nhac', '🎧', 'Âm nhạc'],
  ['st-ve', '🎨', 'Hội họa'], ['st-anh', '📷', 'Nhiếp ảnh'], ['st-bong-da', '⚽', 'Bóng đá'], ['st-bong-ro', '🏀', 'Bóng rổ'],
  ['st-guitar', '🎸', 'Guitar'], ['st-may-tinh', '💻', 'Lập trình'], ['st-thi-nghiem', '🧪', 'Thí nghiệm'], ['st-cup', '🏆', 'Chiến thắng'],
  ['st-muc-tieu', '🎯', 'Mục tiêu'], ['st-tri-tue', '🧠', 'Trí tuệ'], ['st-y-tuong', '💡', 'Ý tưởng'], ['st-du-lich', '✈️', 'Du lịch'],
], 4);

// ---------- Nghệ thuật: dải màu trừu tượng, chỉ là CSS ----------
const mesh = (a: string, b: string, c: string, base: string) =>
  `radial-gradient(circle at 28% 26%,${a},transparent 52%),radial-gradient(circle at 76% 58%,${b},transparent 56%),radial-gradient(circle at 36% 88%,${c},transparent 50%),${base}`;
const ART: Preset[] = ([
  ['nt-cuc-quang', 'Cực quang', mesh('#7cf7d4', '#4f7bff', '#c86bff', '#0d1640')],
  ['nt-hoang-hon', 'Hoàng hôn', mesh('#ffd36e', '#ff5e7e', '#a24bff', '#3b0f3f')],
  ['nt-dai-duong', 'Đại dương', mesh('#7fe7ff', '#1f7bff', '#2de0b0', '#062447')],
  ['nt-keo-ngot', 'Kẹo ngọt', mesh('#ffc6e8', '#a9b8ff', '#fff1a8', '#ff9ccf')],
  ['nt-rung-xanh', 'Rừng xanh', mesh('#d4ff8a', '#1fbf7a', '#0b6e5c', '#06342b')],
  ['nt-dung-nham', 'Dung nham', mesh('#ffe08a', '#ff5a1f', '#c40c4b', '#2a0610')],
  ['nt-thien-ha', 'Thiên hà', mesh('#ff8af1', '#5b5bff', '#00e1ff', '#090a26')],
  ['nt-suong-som', 'Sương sớm', mesh('#ffffff', '#c7e3ff', '#ffd9ec', '#d9e6ff')],
  ['nt-chanh-bac-ha', 'Chanh bạc hà', mesh('#f8ff9a', '#5ff0c0', '#4fb6ff', '#1d6f8f')],
  ['nt-hoa-oai-huong', 'Oải hương', mesh('#f3d1ff', '#9b7bff', '#ff9fd1', '#3c2a7a')],
] as const).map(([id, label, bg]) => ({ id, label, node: art(bg) }));

export const PRESET_GROUPS: PresetGroup[] = [
  { key: 'people', label: 'Nhân vật', items: PEOPLE },
  { key: 'robot', label: 'Robot', items: ROBOTS },
  { key: 'animal', label: 'Động vật', items: ANIMALS },
  { key: 'face', label: 'Biểu cảm', items: FACES },
  { key: 'food', label: 'Đồ ăn', items: FOOD },
  { key: 'nature', label: 'Thiên nhiên', items: NATURE },
  { key: 'hobby', label: 'Sở thích', items: HOBBY },
  { key: 'art', label: 'Nghệ thuật', items: ART },
];
export const PRESETS: Record<string, Preset> = Object.fromEntries(PRESET_GROUPS.flatMap(g => g.items).map(p => [p.id, p]));
