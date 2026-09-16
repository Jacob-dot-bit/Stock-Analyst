import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Portfolio as PortfolioData, PositionSignal, Score } from '../api/types'
import { AllocationTargets } from '../components/AllocationTargets'
import { AttentionCard } from '../components/AttentionCard'
import { OnboardingChecklist } from '../components/OnboardingChecklist'
import { PersonalPolicyPanel } from '../components/PersonalPolicyPanel'
import { PositionsTable } from '../components/PositionsTable'
import { RefreshPanel } from '../components/RefreshPanel'
import { ValueHistoryChart } from '../components/ValueHistoryChart'
import { signClass } from '../format'
import { useI18n } from '../i18n'

export function Portfolio() {
  const { t, formatDate } = useI18n()
  const [data, setData] = useState<PortfolioData | null>(null)
  const [sparklines, setSparklines] = useState<Record<number, number[]>>({})
  const [scores, setScores] = useState<Record<number, Score>>({})
  const [signals, setSignals] = useState<Record<number, PositionSignal>>({})
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const loadSparklines = useCallback(async () => {
    const series = await api.getSparklines()
    setSparklines(Object.fromEntries(series.map((s) => [s.instrument_id, s.closes])))
  }, [])

  const loadScores = useCallback(async () => {
    const list = await api.getScores()
    setScores(Object.fromEntries(list.map((s) => [s.instrument_id, s])))
  }, [])

  const loadSignals = useCallback(async () => {
    const list = await api.getPositionSignals()
    setSignals(Object.fromEntries(list.map((s) => [s.instrument_id, s])))
  }, [])

  const load = useCallback(async () => {
    setError(null)
    try {
      const [portfolio] = await Promise.all([api.getPortfolio(), loadSparklines(), loadScores(), loadSignals()])
      setData(portfolio)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [loadSparklines, loadScores, loadSignals])

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

  // RefreshPanel's live-quote phase already returns the fully recomputed
  // portfolio (market value, P&L, per position — see DEVLOG "Decision 2f.3"),
  // so this replaces state directly rather than issuing a second GET, which
  // would just repeat the same read for no new data. Sparklines are not part
  // of that response, so they still get their own lightweight reload.
  function applyLivePortfolio(portfolio: PortfolioData) {
    setData(portfolio)
    void loadSparklines()
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
        {data?.last_price_refresh_at && (
          <div style={{ marginTop: '0.5rem', fontSize: '0.9rem', opacity: 0.8 }}>
            ✓ {t('portfolio.lastRefresh', {
              date: formatDate(data.last_price_refresh_at),
              time: new Date(data.last_price_refresh_at).toLocaleTimeString('fr-FR', {
                hour: '2-digit',
                minute: '2-digit'
              })
            })}
          </div>
        )}
        <div style={{ marginTop: '0.5rem' }}>
          <Link to="/settings#donnees-portefeuille">{t('portfolio.manageData')}</Link>
        </div>
      </div>

      {error && <div className="notice error">{error}</div>}

      <OnboardingChecklist />

      {data && <Totals data={data} />}

      {data && data.totals.market_value !== null && <AttentionCard />}

      {data && data.totals.market_value !== null && <ValueHistoryChart />}

      {data && data.totals.market_value !== null && <AllocationTargets />}

      {data && data.totals.market_value !== null && <PersonalPolicyPanel />}

      <RefreshPanel onRefreshed={() => void load()} onLivePortfolio={applyLivePortfolio} />

      <div className="card">
        <h2>{t('portfolio.openPositions')}</h2>
        {loading ? (
          <div className="empty">{t('common.loading')}</div>
        ) : (
          data && (
            <PositionsTable
              positions={data.positions}
              baseCurrency={data.totals.base_currency}
              sparklines={sparklines}
              scores={scores}
              signals={signals}
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
          <div className="label" title={t('totals.unrealizedTooltip')}>
            {t('totals.unrealized', { currency: totals.base_currency })}
          </div>
          <div
            className={`value ${totals.unrealized_pl === null ? 'muted' : signClass(totals.unrealized_pl)}`}
          >
            {totals.unrealized_pl === null
              ? t('common.notComputable')
              : formatNumber(totals.unrealized_pl)}
          </div>
        </div>
        <div className="stat">
          <div className="label">{t('totals.realized', { currency: totals.base_currency })}</div>
          <div className={`value ${totals.realized_pl === null ? 'muted' : signClass(totals.realized_pl)}`}>
            {totals.realized_pl === null ? t('common.notComputable') : formatNumber(totals.realized_pl)}
          </div>
        </div>
        <div className="stat">
          <div className="label" title={t('totals.performanceTooltip')}>
            {t('totals.performance')}
          </div>
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
                  <th className="num" title={t('accounts.investedTooltip')}>
                    {t('accounts.invested')}
                  </th>
                  <th className="num">{t('accounts.value')}</th>
                  <th className="num">{t('accounts.unrealized')}</th>
                  <th className="num">{t('accounts.performance')}</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => {
                  const note = account.performance_note ? t(account.performance_note.code, account.performance_note.params) : null
                  const valuationNote = account.valuation_note
                    ? t(account.valuation_note.code, account.valuation_note.params)
                    : null
                  return (
                    <tr key={account.account}>
                      <td>
                        <strong>{account.account}</strong>
                      </td>
                      <td className="num">{account.positions_count}</td>
                      <td className="num">{formatNumber(account.invested_value)}</td>
                      <td className="num" title={valuationNote ?? undefined}>
                        {formatNumber(account.market_value)}
                        {valuationNote && <sup>†</sup>}
                      </td>
                      <td className={`num ${signClass(account.unrealized_pl)}`} title={note ?? undefined}>
                        {formatNumber(account.unrealized_pl)}
                        {note && <sup>*</sup>}
                      </td>
                      <td className={`num ${signClass(account.unrealized_pl_pct)}`} title={note ?? undefined}>
                        {formatSignedPercent(account.unrealized_pl_pct)}
                        {note && <sup>*</sup>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {accounts.some((a) => a.performance_note || a.valuation_note) && (
            <ul className="muted" style={{ marginTop: '0.6rem', marginBottom: 0, paddingLeft: '1.2rem' }}>
              {accounts.flatMap((a) => [
                a.valuation_note && (
                  <li key={`${a.account}-valuation`}>
                    <strong>{a.account}</strong> † — {t(a.valuation_note.code, a.valuation_note.params)}
                  </li>
                ),
                a.performance_note && (
                  <li key={`${a.account}-performance`}>
                    <strong>{a.account}</strong> * — {t(a.performance_note.code, a.performance_note.params)}
                  </li>
                ),
              ])}
            </ul>
          )}
        </div>
      )}

      {totals.has_incomplete_data && (
        <div className="notice warning">
          {t('totals.incomplete', { count: totals.excluded_positions })}
        </div>
      )}

      {totals.has_stale_declared_valuations && (
        <div className="notice warning">{t('totals.staleDeclaredValuations')}</div>
      )}
    </>
  )
}
