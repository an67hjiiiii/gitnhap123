// Thứ tự trang trên thanh bên, từ trên xuống. Dùng để biết chuyển trang là "đi xuống" hay "đi lên"
// (robot rơi xuống / bật lên, trang mới trượt vào theo cùng hướng). Không gian làm việc là trang gốc, đứng đầu.
import type { NavigationTab } from '../types';

// đợt 6: Hồ sơ tài liệu, Kiểm tra mâu thuẫn nằm trong Thư viện; Bộ công cụ mở bằng "/" ở ô chat
export const NAV_ORDER: NavigationTab[] = [
  'orchestration', 'library', 'documents', 'consistency', 'compare', 'toolkit', 'results', 'tasks', 'organization', 'overview', 'settings',
  'evaluation', 'benchmarks', 'rating', 'users', 'db_explorer',
];

export const navIndex = (tab: string | null | undefined) => Math.max(0, NAV_ORDER.indexOf(tab as NavigationTab));

/** 'down' khi trang mới nằm dưới trang cũ trên thanh bên, 'up' khi nằm trên. */
export const navDirection = (from: string | null | undefined, to: string) => (navIndex(to) >= navIndex(from) ? 'down' : 'up');
