// Thứ tự trang trên thanh bên, từ trên xuống. Dùng để biết chuyển trang là "đi xuống" hay "đi lên"
// (robot rơi xuống / bật lên, trang mới trượt vào theo cùng hướng). Không gian làm việc là trang gốc, đứng đầu.
import type { NavigationTab } from '../types';

export const NAV_ORDER: NavigationTab[] = [
  'orchestration', 'organization', 'overview', 'documents', 'toolkit', 'consistency',
  'evaluation', 'benchmarks', 'rating', 'users', 'db_explorer',
];

export const navIndex = (tab: string | null | undefined) => Math.max(0, NAV_ORDER.indexOf(tab as NavigationTab));

/** 'down' khi trang mới nằm dưới trang cũ trên thanh bên, 'up' khi nằm trên. */
export const navDirection = (from: string | null | undefined, to: string) => (navIndex(to) >= navIndex(from) ? 'down' : 'up');
