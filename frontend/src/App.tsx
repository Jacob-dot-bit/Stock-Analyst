import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { Placeholder } from './pages/Placeholder'
import { Portfolio } from './pages/Portfolio'

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Stock Analyst</span>
        <nav className="nav">
          <NavLink to="/portefeuille">Portefeuille</NavLink>
          <NavLink to="/watchlist">Watchlist</NavLink>
          <NavLink to="/pepites">Pépites</NavLink>
        </nav>
      </header>

      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/portefeuille" replace />} />
          <Route path="/portefeuille" element={<Portfolio />} />
          <Route
            path="/watchlist"
            element={
              <Placeholder
                title="Watchlist"
                description="Titres suivis mais non détenus, et analyse du moment d'entrée."
                phase="phase 4"
              />
            }
          />
          <Route
            path="/pepites"
            element={
              <Placeholder
                title="Pépites"
                description="Recherche de titres prometteurs par filtrage sur un univers d'indices."
                phase="phase 5"
              />
            }
          />
        </Routes>
      </main>

      <footer className="disclaimer">
        Cet outil produit des indicateurs à partir de données publiques&nbsp;; ce ne sont pas des
        conseils en investissement. Les décisions restent les vôtres.
      </footer>
    </div>
  )
}
