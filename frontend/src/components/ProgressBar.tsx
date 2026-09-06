import { useI18n } from '../i18n'

/** Structural, not tied to any one status type — `RefreshStatus`,
 * `QuoteStatus`, and `FundamentalsRefreshStatus` all satisfy this shape
 * already, so this component works for any of them without a union. */
interface ProgressStatus {
  total: number
  done: number
  current_symbol?: string | null
}

export function ProgressBar({ phaseLabel, status }: { phaseLabel: string; status: ProgressStatus }) {
  const { t } = useI18n()
  const pct = status.total > 0 ? Math.min(100, Math.round((status.done / status.total) * 100)) : 0

  return (
    <div className="refresh-progress" style={{ marginTop: '1rem' }}>
      <div className="muted" style={{ fontSize: '0.78rem', marginBottom: '0.25rem' }}>
        {phaseLabel}
      </div>
      <div className="refresh-progress-track">
        <div className="refresh-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="refresh-progress-label muted">
        {t('prices.progress', { done: status.done, total: status.total })}
        {status.current_symbol && ` · ${status.current_symbol}`}
      </div>
    </div>
  )
}
