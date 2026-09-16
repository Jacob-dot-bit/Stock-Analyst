import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Liquidity as LiquidityData } from '../api/types'
import { useI18n } from '../i18n'

/**
 * Share of the portfolio priced from a periodically-declared broker
 * statement (Mintos Core P2P, Amundi ESR) rather than a live market quote —
 * the unconditional counterpart to Personal Policy's `declared_valuation`
 * limit (`/policy/gaps` only reports this when a limit is configured, and
 * only the aggregate percentage). Deliberately excludes corporate-action
 * residuals — that is a data-trust fact for Data Health, not a liquidity
 * fact here. See DEVLOG "Decision 3u.67".
 */
export function Liquidity() {
  const { t, formatNumber, formatDate } = useI18n()
  const [data, setData] = useState<LiquidityData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getRiskLiquidity()
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="card">
      <h2>{t('liquidity.title')}</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {t('liquidity.subtitle')}
      </p>

      {error && <div className="notice error">{error}</div>}

      {!error && data && data.sources.length === 0 && <div className="empty">{t('liquidity.empty')}</div>}

      {!error && data && data.sources.length > 0 && (
        <>
          <dl className="position-detail-facts">
            <div>
              <dt>{t('liquidity.total')}</dt>
              <dd>{formatNumber(data.total_declared_weight_percent)}%</dd>
            </div>
          </dl>

          <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
            <table>
              <thead>
                <tr>
                  <th>{t('liquidity.source')}</th>
                  <th className="num">{t('concentration.value')}</th>
                  <th className="num">{t('table.weight')}</th>
                  <th className="num">{t('liquidity.positionsCount')}</th>
                </tr>
              </thead>
              <tbody>
                {data.sources.map((source) => (
                  <tr key={source.reason}>
                    <td>
                      {source.provider_name}
                      {source.has_stale && source.stalest_as_of && (
                        <div className="muted" style={{ fontSize: '0.78rem' }} title={t('valuation.declaredStale', { provider: source.provider_name, date: formatDate(source.stalest_as_of) })}>
                          {t('valuation.declaredStale', { provider: source.provider_name, date: formatDate(source.stalest_as_of) })}
                        </div>
                      )}
                    </td>
                    <td className="num">{formatNumber(source.value)}</td>
                    <td className="num">{formatNumber(source.weight_percent)}%</td>
                    <td className="num">{source.positions_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
