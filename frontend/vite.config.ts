import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // The product API is same-origin in deployment; this keeps local Vite
      // development on the existing loopback FastAPI routes.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
})
