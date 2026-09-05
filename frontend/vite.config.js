import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Two pages, one stylesheet: the app and the printable report both import src/index.css,
// so design tokens, type and print rules live in a single Tailwind file.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      input: { main: resolve(import.meta.dirname, 'index.html'), report: resolve(import.meta.dirname, 'report.html') },
    },
  },
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
})
