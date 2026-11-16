import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The commit this frontend was started (dev server) or built from, shown in
// the footer next to the backend's: after a `git pull`, a service that was
// not restarted shows up as a mismatch. Same override as the backend
// (STOCK_ANALYST_COMMIT) for a copy without its .git directory.
function currentCommit(): string {
  if (process.env.STOCK_ANALYST_COMMIT) return process.env.STOCK_ANALYST_COMMIT.slice(0, 12)
  try {
    return execSync('git log -1 --format=%h', { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    return ''
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_COMMIT__: JSON.stringify(currentCommit()),
  },
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
