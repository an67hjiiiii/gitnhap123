import type { Config } from 'tailwindcss'

// Giao diện chat gốc không dùng lớp Tailwind; phần mở rộng dưới đây phục vụ giao diện Studio (src/studio).
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        indigo: { 50: '#eff5ff', 100: '#dce9ff', 200: '#bbd3ff', 300: '#8eb5ff', 400: '#6594ee', 500: '#3978e8', 600: '#245edb', 700: '#1d4cb2', 800: '#203e84', 900: '#1d3263', 950: '#101d38' },
        slate: { 50: '#f7f9fc', 100: '#eef2f7', 200: '#e0e6ef', 300: '#c6d0df', 400: '#697b94', 500: '#566780', 600: '#45556d', 700: '#34445b', 800: '#233148', 900: '#132139', 950: '#0b1425' },
        dark: { 950: '#06090e', 900: '#0b0f19', 850: '#111827', 800: '#1e293b', 700: '#334155', 600: '#475569' },
        brand: { blue: '#3b82f6', cyan: '#06b6d4', purple: '#8b5cf6', emerald: '#10b981', rose: '#f43f5e', amber: '#f59e0b' },
      },
      fontFamily: {
        sans: ['Be Vietnam Pro', 'sans-serif'],
        mono: ['Fira Code', 'JetBrains Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
