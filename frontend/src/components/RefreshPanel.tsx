import { useState } from 'react'
import { api } from '../api/client'
import type { RefreshReport } from '../api/types'
import { useI18n } from '../i18n'

interface Props {
  onRefreshed: () => void
}

/**
 * Triggers a price refresh and reports, per instrument, what happened.
 *
 * Free providers rate-limit hard — Yahoo returned 429 after four rapid requests — so a
 * refresh works through the list within a time budget and says how many instruments are
 * left. Showing a fake progress bar over that would be dishonest; showing the remainder
 * and letting the user ask again is not.
 */
export function RefreshPanel({ onRefreshed }: Props) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<RefreshReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.refreshPrices()
      setReport(result)
      onRefreshed()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
        <div>
          <h2 style={{ marginBottom: '0.2rem' }}>{t('prices.title')}</h2>
          <span className="muted">{t('prices.subtitle')}</span>
        </div>
        <button className="primary" disabled={busy} onClick={() => void run()}>
          {busy ? t('prices.refreshing') : t('prices.refresh')}
        </button>
      </div>

      {error && (
        <div className="notice error" style={{ marginTop: '1rem', marginBottom: 0 }}>
          {error}
        </div>
      )}

      {report && <RefreshResult report={report} />}
    </div>
  )
}

function RefreshResult({ report }: { report: RefreshReport }) {
  const { t } = useI18n()

  // Only failures are worth listing in full; successes are summarised by the counts.
  const problems = report.outcomes.filter(
    (outcome) => outcome.code !== 'prices.updated' && outcome.code !== 'prices.alreadyFresh',
  )

  return (
    <div
      className={`notice ${report.remaining > 0 || report.failed > 0 ? 'warning' : 'info'}`}
      style={{ marginTop: '1rem', marginBottom: 0 }}
    >
      {t('prices.summary', {
        updated: report.updated,
        skipped: report.skipped,
        failed: report.failed,
      })}

      {report.remaining > 0 && (
        <div style={{ marginTop: '0.4rem' }}>
          <strong>{t('prices.remaining', { count: report.remaining })}</strong>
        </div>
      )}

      {problems.length > 0 && (
        <ul>
          {problems.map((outcome, index) => (
            <li key={index}>{t(outcome.code, outcome.params)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
