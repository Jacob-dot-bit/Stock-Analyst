import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Portfolio as PortfolioData } from '../api/types'
import { ImportPanel } from '../components/ImportPanel'
import { ManualPositionForm } from '../components/ManualPositionForm'
import { PositionsTable } from '../components/PositionsTable'
import { UnresolvedPanel } from '../components/UnresolvedPanel'
import { signClass } from '../format'
import { useI18n } from '../i18n'

export function Portfolio() {
  const { t, formatDate } = useI18n()
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
        <h1>{t('portfolio.title')}</h1>
        <p>
          {t('portfolio.subtitle')}
          {data?.last_import_at &&
            ` ${t('portfolio.lastImport', { date: formatDate(data.last_import_at) })}`}
        </p>
      </div>

      {error && <div className="notice error">{error}</div>}

      {data && <Totals data={data} />}

      <ImportPanel onImported={() => void load()} />

      {data && <UnresolvedPanel instruments={data.unresolved_symbols} onUpdated={() => void load()} />}

      <ManualPositionForm onCreated={() => void load()} />

      <div className="card">
        <h2>{t('portfolio.openPositions')}</h2>
        {loading ? (
          <div className="empty">{t('common.loading')}</div>
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
  const { t, formatNumber, formatSignedPercent } = useI18n()
  const { totals, accounts } = data

  return (
    <>
      <div className="stat-grid" style={{ marginBottom: '1.1rem' }}>
        <div className="stat">
          <div className="label">{t('totals.positions')}</div>
          <div className="value">{totals.positions_count}</div>
        </div>
        <div className="stat">
          <div className="label">{t('totals.marketValue', { currency: totals.base_currency })}</div>
          <div className={`value${totals.market_value === null ? ' muted' : ''}`}>
            {totals.market_value === null ? t('common.notComputable') : formatNumber(totals.market_value)}
          </div>
        </div>
        <div className="stat">
          <div className="label">{t('totals.unrealized', { currency: totals.base_currency })}</div>
          <div
            className={`value ${totals.unrealized_pl === null ? 'muted' : signClass(totals.unrealized_pl)}`}
          >
            {totals.unrealized_pl === null
              ? t('common.notComputable')
              : formatNumber(totals.unrealized_pl)}
          </div>
        </div>
        <div className="stat">
          <div className="label">{t('totals.performance')}</div>
          <div
            className={`value ${
              totals.unrealized_pl_pct === null ? 'muted' : signClass(totals.unrealized_pl_pct)
            }`}
          >
            {totals.unrealized_pl_pct === null
              ? t('common.notComputable')
              : formatSignedPercent(totals.unrealized_pl_pct)}
          </div>
        </div>
      </div>

      {accounts.length > 1 && (
        <div className="card">
          <h2>{t('accounts.title')}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('accounts.account')}</th>
                  <th className="num">{t('accounts.positions')}</th>
                  <th className="num">{t('accounts.invested')}</th>
                  <th className="num">{t('accounts.value')}</th>
                  <th className="num">{t('accounts.unrealized')}</th>
                  <th className="num">{t('accounts.performance')}</th>
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
                      {formatSignedPercent(account.unrealized_pl_pct)}
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
          {t('totals.incomplete', { count: totals.excluded_positions })}
        </div>
      )}
    </>
  )
}
