import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { PredictionBackfillReport, PredictionBackfillStatus } from '../api/types'
import { ProgressBar } from './ProgressBar'
import { useI18n } from '../i18n'

const POLL_INTERVAL_MS = 800

/**
 * Phase 1 of a real, backtestable Discovery prediction: pulls several
 * years of daily price history for the already-priced universe. Deliberately
 * price-only — see `app/prediction/service.py`'s module docstring for why
 * fundamentals can't be used yet without introducing lookahead bias (DEVLOG
 * "Decision 3u.22"). Same polling shape as `FundamentalsRefreshButton.tsx`:
 * the `POST` blocks for the whole run (~87 instruments, one throttled call
 * each — several minutes), so `GET .../status` gives a real progress bar
 * polled from a separate request.
 */
export function PredictionBackfillButton() {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<PredictionBackfillStatus | null>(null)
  const [report, setReport] = useState<PredictionBackfillReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPolling() {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => {
    let cancelled = false

    async function resume() {
      const current = await api.getPredictionBackfillStatus().catch(() => null)
      if (cancelled || !current?.running) return

      setBusy(true)
      setStatus(current)
      pollRef.current = setInterval(() => {
        void api
          .getPredictionBackfillStatus()
          .then((next) => {
            setStatus(next)
            if (!next.running) {
              stopPolling()
              setReport(next.report)
              setBusy(false)
            }
          })
          .catch(() => {})
      }, POLL_INTERVAL_MS)
    }

    void resume()
    return () => {
      cancelled = true
      stopPolling()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only resume check
  }, [])

  async function run() {
    setBusy(true)
    setError(null)
    setStatus(null)
    setReport(null)

    stopPolling()
    pollRef.current = setInterval(() => {
      void api.getPredictionBackfillStatus().then(setStatus).catch(() => {})
    }, POLL_INTERVAL_MS)

    try {
      const result = await api.backfillPredictionHistory()
      setReport(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      stopPolling()
      setBusy(false)
      void api.getPredictionBackfillStatus().then(setStatus).catch(() => {})
    }
  }

  return (
    <div>
      <h3 style={{ marginBottom: '0.2rem' }}>{t('prediction.title')}</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
        {t('prediction.description')}
      </p>
      <div className="form-row">
        <button disabled={busy} onClick={() => void run()}>
          {busy ? t('prediction.running') : t('prediction.backfill')}
        </button>
      </div>

      {busy && status && status.total > 0 && <ProgressBar phaseLabel={t('prediction.running')} status={status} />}

      {error && (
        <div className="notice error" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          {error}
        </div>
      )}

      {report?.already_running && (
        <div className="notice warning" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          {t('prediction.alreadyRunning')}
        </div>
      )}

      {report && !report.already_running && (
        <div className={`notice ${report.failed > 0 ? 'warning' : 'info'}`} style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          {t('prediction.backfillResult', {
            updated: report.updated,
            failed: report.failed,
            barsAdded: report.bars_added,
          })}
        </div>
      )}
    </div>
  )
}
