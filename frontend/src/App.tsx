import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { LanguageSwitcher } from './components/LanguageSwitcher'
import { useI18n } from './i18n'
import { Placeholder } from './pages/Placeholder'
import { Portfolio } from './pages/Portfolio'

export default function App() {
  const { t } = useI18n()

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">{t('app.title')}</span>
        <nav className="nav">
          <NavLink to="/portfolio">{t('nav.portfolio')}</NavLink>
          <NavLink to="/watchlist">{t('nav.watchlist')}</NavLink>
          <NavLink to="/gems">{t('nav.gems')}</NavLink>
        </nav>
        <LanguageSwitcher />
      </header>

      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/portfolio" replace />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route
            path="/watchlist"
            element={
              <Placeholder
                titleKey="watchlist.title"
                descriptionKey="watchlist.description"
                phaseKey="phase.4"
              />
            }
          />
          <Route
            path="/gems"
            element={
              <Placeholder titleKey="gems.title" descriptionKey="gems.description" phaseKey="phase.5" />
            }
          />
        </Routes>
      </main>

      <footer className="disclaimer">{t('app.disclaimer')}</footer>
    </div>
  )
}
