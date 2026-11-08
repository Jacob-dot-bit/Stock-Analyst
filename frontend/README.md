# Stock Analyst — frontend

React 19 + TypeScript, built with Vite. Setup and the overall picture are in the
[main README](../README.md); this file only covers working on the UI.

```bash
npm install
npm run dev     # http://localhost:5173, proxies /api to the backend on :8000
npm run lint    # oxlint
npm run build   # type-check (tsc -b) then production build into dist/
```

The backend must be running for the pages to show data.

## Layout

| Path | Content |
|---|---|
| `src/pages/` | One component per route (Portfolio, Watchlist, Screener, Weekly, …), loaded on demand |
| `src/components/` | Shared panels, tables and charts |
| `src/api/` | Typed client for the backend API |
| `src/i18n/` | Translations: `en.ts`, `fr.ts`, `pl.ts` (same keys in all three) |
| `src/format.ts` | Number, currency and date formatting for the current locale |
| `src/theme.ts` | Dark/light theme, saved in `localStorage` |
| `src/index.css` | Design tokens (CSS variables) and shared layout classes |

## Conventions

- Every visible string goes through `t()`. A new key must be added to all three
  catalogues (typed as `Catalogue`), or the type check fails.
- Missing values are shown as missing (`—`), never as `0`.
- The app describes facts; no text phrases an indicator as an order to buy or sell.
