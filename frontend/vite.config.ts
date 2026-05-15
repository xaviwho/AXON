import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
// The /api/* and /live proxies let the dashboard work from both the
// host browser (origin localhost:5173 → Vite → console_api on the host)
// and the recording container's browser (origin host.docker.internal:5173
// → Vite on the host → console_api), without the page needing to know
// which environment it's running in. See demos/recordings/record_all.sh.
const API_TARGET = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8008'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Vite 7 blocks requests whose Host header isn't in this list — needed
    // because the recording container reaches the dev server via
    // `host.docker.internal`. Loopback is fine; we don't expose to LAN.
    allowedHosts: ['localhost', '127.0.0.1', 'host.docker.internal'],
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
      '/live': {
        target: API_TARGET,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
