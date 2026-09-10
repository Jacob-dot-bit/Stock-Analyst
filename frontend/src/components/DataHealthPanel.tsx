import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DataHealth, DataHealthRow, DataHealthSeverity } from '../api/types'
import { useI18n } from '../i18n'

//: Which CSS badge class each overall severity maps to. "action_required"
//: is the one real error state here — the only place in this panel a red
//: tag is warranted, since it means a number may genuinely be wrong or
//: missing (mirrors `.price-status-error`'s own use of `--negative`).
//: Never red for "attention": a candidate corporate action or a merely
//: dated declared valuation is still usable data, not a broken one.
const SEVERITY_BADGE_CLASS: Record<DataHealthSeverity, string> = {
  info: 'confidence-confirmed',
  attention: 'confidence-review',
  action_required: 'negative',
  not_applicable: 'confidence-neutral',
}

function SeverityBadge({ severity }: { severity: DataHealthSeverity }) {
  const { t } = useI18n()
  return <span className={`tag ${SEVERITY_BADGE_CLASS[severity]}`}>{t(`dataHealth.severity.${severity}`)}</span>
}

function ValuationCell({ row }: { row: DataHealthRow }) {
  const { t, formatDate } = useI18n()
  const { valuation } = row
  const kindLabel = t(`dataHealth.valuation.kind.${valuation.kind}`)
  if (valuation.kind === 'unavailable') {
    return <span className="muted">{kindLabel}</span>
  }
  const parts = [kindLabel]
  if (valuation.source) parts.push(valuation.source)
  if (valuation.as_of) parts.push(formatDate(valuation.as_of))
  return (
    <div>
      <div>{parts.join(' — ')}</div>
      {valuation.freshness !== 'fresh' && (
        <div className="muted" style={{ fontSize: '0.8rem' }}>
          {t(`dataHealth.valuation.freshness.${valuation.freshness}`)}
        </div>
      )}
    </div>
  )
}

function CorporateActionsCell({ row }: { row: DataHealthRow }) {
  const { t } = useI18n()
  const { corporate_actions: ca } = row
  if (ca.status === 'not_applicable') return <span className="muted">—</span>
  const label = t(`dataHealth.corporateActions.status.${ca.status}`)
  if (ca.confirmed_events === 0 && ca.outstanding_events === 0) {
    return <span>{label}</span>
  }
  return (
    <div>
      <div>{label}</div>
      <div className="muted" style={{ fontSize: '0.8rem' }}>
        {t('dataHealth.corporateActions.eventCounts', {
          confirmed: ca.confirmed_events,
          outstanding: ca.outstanding_events,
        })}
      </div>
    </div>
  )
}

/**
 * Per-instrument data-quality and corporate-action trust report for held
 * positions — "can I trust the numbers valuing what I actually own?"
 * Supersedes the v1 category-list panel (DEVLOG "Decision 3u.33"/"3u.50")
 * with one row per instrument carrying two independent signals (valuation
 * freshness, corporate-action confirmation) resolved into a single overall
 * severity. See DEVLOG "Decision 3u.58". Placed above `UnresolvedPanel` in
 * Settings, same position as v1.
 */
export function DataHealthPanel() {
  const { t } = useI18n()
  const [data, setData] = useState<DataHealth | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getDataHealth()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  if (error || data === null) return null

  const { summary, rows } = data

  return (
    <div className="card">
      <h2>{t('dataHealth.title')}</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {t('dataHealth.subtitle')}
      </p>

      {rows.length === 0 ? (
        <p className="muted" style={{ marginTop: 0 }}>
          {t('dataHealth.empty')}
        </p>
      ) : (
        <>
          <div className="data-health-summary">
            {summary.action_required_count > 0 && (
              <span className="tag negative">
                {t('dataHealth.summary.actionRequired', { count: summary.action_required_count })}
              </span>
            )}
            {summary.attention_count > 0 && (
              <span className="tag confidence-review">
                {t('dataHealth.summary.attention', { count: summary.attention_count })}
              </span>
            )}
            <span className="tag confidence-confirmed">
              {t('dataHealth.summary.info', { count: summary.info_count })}
            </span>
            {summary.not_applicable_count > 0 && (
              <span className="tag confidence-neutral">
                {t('dataHealth.summary.notApplicable', { count: summary.not_applicable_count })}
              </span>
            )}
          </div>

          <div className="table-wrap" style={{ marginTop: '0.9rem' }}>
            <table>
              <thead>
                <tr>
                  <th>{t('dataHealth.column.instrument')}</th>
                  <th>{t('dataHealth.column.valuation')}</th>
                  <th>{t('dataHealth.column.corporateActions')}</th>
                  <th>{t('dataHealth.column.severity')}</th>
                  <th>{t('dataHealth.column.recommendedAction')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.instrument_id}>
                    <td>{row.name ? `${row.symbol} — ${row.name}` : row.symbol}</td>
                    <td>
                      <ValuationCell row={row} />
                    </td>
                    <td>
                      <CorporateActionsCell row={row} />
                    </td>
                    <td>
                      <SeverityBadge severity={row.severity} />
                    </td>
                    <td className="muted">
                      {row.recommended_action ? t(`dataHealth.action.${row.recommended_action}`) : '—'}
                    </td>
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
