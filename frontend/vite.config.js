import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Dev'da CORS bilan ovora bo'lmaslik uchun backend'ga proxy.
      '/api': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8001', ws: true },
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
})
