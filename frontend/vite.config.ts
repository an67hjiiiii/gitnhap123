// Biến môi trường Node chỉ dùng lúc chạy Vite (API_TARGET); khai báo tối thiểu để không cần @types/node.
declare const process: { env: Record<string, string | undefined> }
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // The product API is same-origin in deployment; this keeps local Vite
      // development on the existing loopback FastAPI routes.
      "/api": { target: process.env.API_TARGET || "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  // Bản phát hành chạy bằng `npm run preview` (mã đã tối ưu) với cùng cách chuyển tiếp API.
  preview: {
    proxy: {
      "/api": { target: process.env.API_TARGET || "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
})
