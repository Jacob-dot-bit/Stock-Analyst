import { Suspense, lazy, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AlertsBell } from './components/AlertsBell'
import { LanguageSwitcher } from './components/LanguageSwitcher'
import { SkeletonPage } from './components/Skeleton'
import { ThemeToggle } from './components/ThemeToggle'
import { useI18n } from './i18n'

// Each page is its own chunk, fetched the first time it is opened, so the
// first screen doesn't wait for the code of the nine others.
const Dividends = lazy(() => import('./pages/Dividends').then((m) => ({ default: m.Dividends })))
const Journal = lazy(() => import('./pages/Journal').then((m) => ({ default: m.Journal })))
const Portfolio = lazy(() => import('./pages/Portfolio').then((m) => ({ default: m.Portfolio })))
const Risques = lazy(() => import('./pages/Risques').then((m) => ({ default: m.Risques })))
const Screener = lazy(() => import('./pages/Screener').then((m) => ({ default: m.Screener })))
const Settings = lazy(() => import('./pages/Settings'))
const TaxPrep = lazy(() => import('./pages/TaxPrep').then((m) => ({ default: m.TaxPrep })))
const Transactions = lazy(() => import('./pages/Transactions').then((m) => ({ default: m.Transactions })))
const Watchlist = lazy(() => import('./pages/Watchlist').then((m) => ({ default: m.Watchlist })))
const Weekly = lazy(() => import('./pages/Weekly').then((m) => ({ default: m.Weekly })))

// Browser tab title per page, so several open tabs (and the history list)
// can be told apart.
const PAGE_TITLES: Record<string, string> = {
  '/portfolio': 'nav.portfolio',
  '/week': 'nav.weekly',
  '/transactions': 'nav.transactions',
  '/dividends': 'dividends.title',
  '/watchlist': 'nav.watchlist',
  '/gems': 'nav.gems',
  '/tax-prep': 'nav.taxPrep',
  '/risk': 'nav.risk',
  '/journal': 'nav.journal',
  '/settings': 'settings.title',
}

export default function App() {
  const { t } = useI18n()
  const location = useLocation()
  // Phones get a collapsed menu behind one button instead of nine wrapped
  // links eating the top of every page. Closed again on every navigation.
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    const key = PAGE_TITLES[location.pathname]
    document.title = key ? `${t(key)} · ${t('app.title')}` : t('app.title')
  }, [location.pathname, t])

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">{t('app.title')}</span>
        <button
          type="button"
          className="nav-toggle"
          aria-expanded={menuOpen}
          aria-controls="main-nav"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            {menuOpen ? (
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            ) : (
              <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            )}
          </svg>
          <span className="visually-hidden">{t('nav.menu')}</span>
        </button>
        <nav id="main-nav" className={`nav${menuOpen ? ' open' : ''}`} aria-label={t('nav.menu')}>
          <NavLink to="/portfolio">{t('nav.portfolio')}</NavLink>
          <NavLink to="/week">{t('nav.weekly')}</NavLink>
          <NavLink to="/transactions">{t('nav.transactions')}</NavLink>
          <NavLink to="/watchlist">{t('nav.watchlist')}</NavLink>
          <NavLink to="/gems">{t('nav.gems')}</NavLink>
          <NavLink to="/tax-prep">{t('nav.taxPrep')}</NavLink>
          <NavLink to="/risk">{t('nav.risk')}</NavLink>
          <NavLink to="/journal">{t('nav.journal')}</NavLink>
          <NavLink to="/settings">{t('settings.title')}</NavLink>
        </nav>
        <AlertsBell />
        <div className="topbar-controls">
          <LanguageSwitcher />
          <ThemeToggle />
        </div>
      </header>

      <main className="content">
        <Suspense fallback={<SkeletonPage />}>
          <Routes>
            <Route path="/" element={<Navigate to="/portfolio" replace />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/week" element={<Weekly />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/dividends" element={<Dividends />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/watchlist" element={<Watchlist />} />
            <Route path="/gems" element={<Screener />} />
            <Route path="/tax-prep" element={<TaxPrep />} />
            <Route path="/risk" element={<Risques />} />
            <Route path="/journal" element={<Journal />} />
          </Routes>
        </Suspense>
      </main>

      <footer className="disclaimer">{t('app.disclaimer')}</footer>
    </div>
  )
}
