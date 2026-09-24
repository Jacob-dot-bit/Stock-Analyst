import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Off (loopback-only) by default — matches the backend's own
    // loopback-only middleware (app/main.py). Set VITE_DEV_HOST_ALL=true in
    // your own shell/local .env (never commit it) to bind all interfaces
    // instead, e.g. so a local Docker container (and its
    // host.docker.internal) can reach this dev server. Off by default so
    // cloning this repo never silently exposes the dev server beyond this
    // machine.
    host: process.env.VITE_DEV_HOST_ALL === 'true',
    // The backend runs on 8000: proxying /api keeps everything on a single origin
    // in the browser, so CORS never enters the picture.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
