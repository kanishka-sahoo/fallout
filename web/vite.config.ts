import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const api = process.env.FALLOUT_API ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 900 }, // sigma + graphology are one WebGL bundle by design
  server: {
    port: 5173,
    proxy: {
      '/api': api,
      '/ws': { target: api.replace(/^http/, 'ws'), ws: true },
    },
  },
})
