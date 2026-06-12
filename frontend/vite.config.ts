/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Forward /api to the FastAPI backend so the browser sees one origin
    // (no CORS preflight) during development. The backend has no /api
    // prefix, so it is stripped here. ws:true also proxies /api/ws/….
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        ws: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/tests/setup.ts'],
  },
})
