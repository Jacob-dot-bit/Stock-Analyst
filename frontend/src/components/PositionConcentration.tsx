import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { PositionConcentration as PositionConcentrationRow } from '../api/types'
import { useI18n } from '../i18n'

/**
 * Every held position's share of total portfolio value, largest first — the
 * unconditional, always-visible counterpart to Personal Policy's `line`
 * limit (`/policy/gaps` only reports a *breach* of a *configured* line
 * limit; this reports the top N regardless of whether any limit exists).
 * Purely descriptive: no color-coded "risk tier," no implicit verdict. See
 * DEVLOG "Decision 3u.67".
 */
export function PositionConcentration() {
  const { t, formatNumber } = useI18n()
  const [rows, setRows] = useState<PositionConcentrationRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getRiskConcentration()
      .then((result) => {
        if (!cancelled) setRows(result)
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
      <h2>{t('concentration.title')}</h2>

      {error && <div className="notice error">{error}</div>}

      {!error && rows && rows.length === 0 && <div className="empty">{t('concentration.empty')}</div>}

      {!error && rows && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('table.instrument')}</th>
                <th>{t('table.type')}</th>
                <th className="num">{t('concentration.value')}</th>
                <th className="num">{t('table.weight')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.instrument_id}>
                  <td>
                    <strong>{row.symbol}</strong>
                    {row.name && (
                      <div className="muted" style={{ fontSize: '0.78rem' }}>
                        {row.name}
                      </div>
                    )}
                  </td>
                  <td>{row.category ? t(`breakdown.category.${row.category}`) : '—'}</td>
                  <td className="num">{formatNumber(row.value)}</td>
                  <td className="num">{formatNumber(row.weight_percent)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
