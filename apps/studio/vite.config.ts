import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Override to point a dev UI at another server instance
const SERVER = process.env.STUDIO_SERVER ?? 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The repo lives on a USB drive whose change notifications get dropped; polling is reliable
    watch: { usePolling: true, interval: 250 },
    proxy: {
      // `ws: true` forwards the /api/ws WebSocket upgrade as well as plain requests
      '/api': { target: SERVER, changeOrigin: true, ws: true },
      '/files': { target: SERVER, changeOrigin: true },
    },
  },
  css: {
    modules: { localsConvention: 'camelCaseOnly' },
  },
})
