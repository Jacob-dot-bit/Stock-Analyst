import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { AlertsBell } from './components/AlertsBell'
import { LanguageSwitcher } from './components/LanguageSwitcher'
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

export default function App() {
  const { t } = useI18n()

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">{t('app.title')}</span>
        <nav className="nav">
          <NavLink to="/portfolio">{t('nav.portfolio')}</NavLink>
          <NavLink to="/transactions">{t('nav.transactions')}</NavLink>
          <NavLink to="/watchlist">{t('nav.watchlist')}</NavLink>
          <NavLink to="/gems">{t('nav.gems')}</NavLink>
          <NavLink to="/tax-prep">{t('nav.taxPrep')}</NavLink>
          <NavLink to="/risk">{t('nav.risk')}</NavLink>
          <NavLink to="/journal">{t('nav.journal')}</NavLink>
          <NavLink to="/settings">{t('settings.title')}</NavLink>
        </nav>
        <AlertsBell />
        <LanguageSwitcher />
      </header>

      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/portfolio" replace />} />
          <Route path="/portfolio" element={<Portfolio />} />
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
