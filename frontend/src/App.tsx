import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AlertsBell } from './components/AlertsBell'
import { LanguageSwitcher } from './components/LanguageSwitcher'
import { ThemeToggle } from './components/ThemeToggle'
import { useI18n } from './i18n'
import { Dividends } from './pages/Dividends'
import { Journal } from './pages/Journal'
import { Portfolio } from './pages/Portfolio'
import { Risques } from './pages/Risques'
import { Screener } from './pages/Screener'
import Settings from './pages/Settings'
import { TaxPrep } from './pages/TaxPrep'
import { Transactions } from './pages/Transactions'
import { Watchlist } from './pages/Watchlist'
import { Weekly } from './pages/Weekly'

export default function App() {
  const { t } = useI18n()
  const location = useLocation()
  // Phones get a collapsed menu behind one button instead of nine wrapped
  // links eating the top of every page. Closed again on every navigation.
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

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
      </main>

      <footer className="disclaimer">{t('app.disclaimer')}</footer>
    </div>
  )
}
