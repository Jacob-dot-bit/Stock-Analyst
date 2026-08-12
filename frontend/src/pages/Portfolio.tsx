import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Portfolio as PortfolioData } from '../api/types'
import { ImportPanel } from '../components/ImportPanel'
import { ManualPositionForm } from '../components/ManualPositionForm'
import { PositionsTable } from '../components/PositionsTable'
import { UnresolvedPanel } from '../components/UnresolvedPanel'
import { formatDate, formatNumber, formatPercent, signClass } from '../format'

export function Portfolio() {
  const [data, setData] = useState<PortfolioData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setError(null)
    try {
      setData(await api.getPortfolio())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function handleDelete(id: number) {
    try {
      await api.deletePosition(id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Portefeuille</h1>
        <p>
          Positions détenues et résultat latent.
          {data?.last_import_at && ` Dernier import : ${formatDate(data.last_import_at)}.`}
        </p>
      </div>

      {error && <div className="notice error">{error}</div>}

      {data && <Totals data={data} />}

      <ImportPanel onImported={() => void load()} />

      {data && <UnresolvedPanel instruments={data.unresolved_symbols} onUpdated={() => void load()} />}

      <ManualPositionForm onCreated={() => void load()} />

      <div className="card">
        <h2>Positions ouvertes</h2>
        {loading ? (
          <div className="empty">Chargement…</div>
        ) : (
          data && (
            <PositionsTable
              positions={data.positions}
              baseCurrency={data.totals.base_currency}
              onDelete={(id) => void handleDelete(id)}
              onUpdated={() => void load()}
            />
          )
        )}
      </div>
    </>
  )
}

function Totals({ data }: { data: PortfolioData }) {
  const { totals, accounts } = data

  return (
    <>
      <div className="stat-grid" style={{ marginBottom: '1.1rem' }}>
        <div className="stat">
          <div className="label">Positions</div>
          <div className="value">{totals.positions_count}</div>
        </div>
        <div className="stat">
          <div className="label">Valeur de marché ({totals.base_currency})</div>
          <div className={`value${totals.market_value === null ? ' muted' : ''}`}>
            {totals.market_value === null ? 'non calculable' : formatNumber(totals.market_value)}
          </div>
        </div>
        <div className="stat">
          <div className="label">Résultat latent ({totals.base_currency})</div>
          <div className={`value ${totals.unrealized_pl === null ? 'muted' : signClass(totals.unrealized_pl)}`}>
            {totals.unrealized_pl === null ? 'non calculable' : formatNumber(totals.unrealized_pl)}
          </div>
        </div>
        <div className="stat">
          <div className="label">Performance</div>
          <div className={`value ${totals.unrealized_pl_pct === null ? 'muted' : signClass(totals.unrealized_pl_pct)}`}>
            {totals.unrealized_pl_pct === null ? 'non calculable' : formatPercent(totals.unrealized_pl_pct)}
          </div>
        </div>
      </div>

      {accounts.length > 1 && (
        <div className="card">
          <h2>Par compte</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Compte</th>
                  <th className="num">Positions</th>
                  <th className="num">Investi</th>
                  <th className="num">Valeur</th>
                  <th className="num">Latent</th>
                  <th className="num">Perf.</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => (
                  <tr key={account.account}>
                    <td>
                      <strong>{account.account}</strong>
                    </td>
                    <td className="num">{account.positions_count}</td>
                    <td className="num">{formatNumber(account.invested_value)}</td>
                    <td className="num">{formatNumber(account.market_value)}</td>
                    <td className={`num ${signClass(account.unrealized_pl)}`}>
                      {formatNumber(account.unrealized_pl)}
                    </td>
                    <td className={`num ${signClass(account.unrealized_pl_pct)}`}>
                      {formatPercent(account.unrealized_pl_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {totals.has_incomplete_data && (
        <div className="notice warning">
          {totals.excluded_positions} position(s) ne fournissent pas de valorisation — typiquement
          des lignes saisies à la main. Elles sont <strong>exclues des totaux</strong> plutôt que
          comptées à zéro, ce qui donnerait un total faux à l'apparence juste. Les cours de marché
          seront branchés à l'étape suivante du projet.
        </div>
      )}
    </>
  )
}
