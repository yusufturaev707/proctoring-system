import { defineConfig } from 'vite'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * React Scan (`npm run dev:scan`) — FAQAT dev serverda va `--mode scan` da.
 *
 * Skript `index.html` ga ilova kodidan OLDIN qo'yiladi: React Scan
 * React'dan oldin yuklanishi shart (DevTools hook). Modul skriptlar
 * hujjat tartibida bajariladi, ya'ni `main.tsx` dan keyin emas.
 * Production build'ga ham, oddiy `npm run dev` ga ham hech narsa
 * qo'shilmaydi (`src/devtools/reactScan.ts`).
 */
function reactScanPlugin(enabled: boolean): Plugin {
  return {
    name: 'react-scan-dev',
    apply: 'serve',
    transformIndexHtml() {
      if (!enabled) return []
      return [{
        tag: 'script',
        attrs: { type: 'module', src: '/src/devtools/reactScan.ts' },
        injectTo: 'head-prepend' as const,
      }]
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), reactScanPlugin(mode === 'scan')],
  server: {
    port: 5175,
    proxy: {
      // Dev'da CORS bilan ovora bo'lmaslik uchun backend'ga proxy.
      '/api': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8003', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // MUI va grafika kutubxonalari katta — ularni alohida chunk'ga
        // ajratamiz, shunda ilova kodi o'zgarganda ular qayta yuklanmaydi.
        manualChunks: {
          mui: ['@mui/material', '@mui/icons-material'],
          grid: ['@mui/x-data-grid'],
          charts: ['recharts'],
          vendor: ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query'],
        },
      },
    },
  },
}))
