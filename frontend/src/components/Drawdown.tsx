import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Drawdown as DrawdownData } from '../api/types'
import { useI18n } from '../i18n'

/**
 * Largest peak-to-trough decline in real historical portfolio value — from
 * the same `Lot`-replay series `ValueHistoryChart` already shows. Nowhere
 * else in this app computes this. "Recovered" means the value reached back
 * to the pre-drawdown peak at some point after the trough — a historical
 * fact, never "is it at that peak right now" (which can differ if it has
 * since dropped again). See DEVLOG "Decision 3u.67".
 */
export function Drawdown() {
  const { t, formatNumber, formatDate } = useI18n()
  const [data, setData] = useState<DrawdownData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getRiskDrawdown()
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
      <h2>{t('drawdown.title')}</h2>

      {error && <div className="notice error">{error}</div>}

      {!error && data && data.insufficient_history && <div className="empty">{t('drawdown.insufficientHistory')}</div>}

      {!error && data && !data.insufficient_history && (
        <dl className="position-detail-facts">
          <div>
            <dt>{t('drawdown.maxDrawdown')}</dt>
            <dd>{data.max_drawdown_pct !== null ? `${formatNumber(data.max_drawdown_pct)}%` : '—'}</dd>
          </div>
          <div>
            <dt>{t('drawdown.peak')}</dt>
            <dd>
              {data.peak_date && data.peak_value !== null
                ? `${formatDate(data.peak_date)} — ${formatNumber(data.peak_value)}`
                : '—'}
            </dd>
          </div>
          <div>
            <dt>{t('drawdown.trough')}</dt>
            <dd>
              {data.trough_date && data.trough_value !== null
                ? `${formatDate(data.trough_date)} — ${formatNumber(data.trough_value)}`
                : '—'}
            </dd>
          </div>
          <div>
            <dt>{t('drawdown.recovery')}</dt>
            <dd>
              {data.max_drawdown_pct === 0
                ? t('drawdown.noneObserved')
                : data.recovered && data.recovered_date
                  ? t('drawdown.recoveredOn', { date: formatDate(data.recovered_date) })
                  : t('drawdown.notRecovered')}
            </dd>
          </div>
        </dl>
      )}
    </div>
  )
}
