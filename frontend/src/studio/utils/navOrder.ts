// Thứ tự trang trên thanh bên, từ trên xuống. Dùng để biết chuyển trang là "đi xuống" hay "đi lên"
// (robot rơi xuống / bật lên, trang mới trượt vào theo cùng hướng). Không gian làm việc là trang gốc, đứng đầu.
import type { NavigationTab } from '../types';

export const NAV_ORDER: NavigationTab[] = [
  // Nhóm 1: Làm việc
  'orchestration', 'toolkit', 'office',
  // Nhóm 2: Tri thức & Quản lý
  'library', 'documents', 'consistency', 'compare', 'results', 'tasks', 'overview', 'organization',
  // Nhóm 3: Nghiên cứu (Phòng thí nghiệm)
  'evaluation', 'benchmarks', 'rating',
  // Tiện ích mở từ thanh trên (Thông báo, Hướng dẫn nhanh, Cài đặt)
  'notifications', 'guide', 'settings',
  // Cổng quản trị (dự phòng tương thích)
  'users', 'db_explorer',
];

export const navIndex = (tab: string | null | undefined) => Math.max(0, NAV_ORDER.indexOf(tab as NavigationTab));

/** 'down' khi trang mới nằm dưới trang cũ trên thanh bên, 'up' khi nằm trên. */
export const navDirection = (from: string | null | undefined, to: string) => (navIndex(to) >= navIndex(from) ? 'down' : 'up');
