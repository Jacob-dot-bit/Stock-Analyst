import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { FundamentalsRefreshReport, FundamentalsRefreshStatus } from '../api/types'
import { ProgressBar } from './ProgressBar'
import { useI18n } from '../i18n'

interface Props {
  onRefreshed: () => void
}

const POLL_INTERVAL_MS = 800

/**
 * Triggers a fundamentals fetch from SEC EDGAR (US) and ESEF (Europe) for
 * held stocks. Polled the same way `RefreshPanel` polls price refresh: the
 * `POST` itself still blocks until done, but a cold run — ESEF's first
 * entity-index load in a fresh process pays a one-time ~37-request cost — is
 * tens of seconds, not the sub-second case a single unpolled request used to
 * assume, so this needs the same real (never simulated) progress bar.
 */
export function FundamentalsRefreshButton({ onRefreshed }: Props) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<FundamentalsRefreshStatus | null>(null)
  const [report, setReport] = useState<FundamentalsRefreshReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPolling() {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  // Progress lives server-side (process-wide, not tied to this component),
  // so navigating away mid-refresh and back should resume showing it rather
  // than assuming idle — same reasoning as `RefreshPanel.tsx`'s mount effect.
  useEffect(() => {
    let cancelled = false

    async function resume() {
      const current = await api.getFundamentalsRefreshStatus().catch(() => null)
      if (cancelled || !current?.running) return

      setBusy(true)
      setStatus(current)
      pollRef.current = setInterval(() => {
        void api
          .getFundamentalsRefreshStatus()
          .then((next) => {
            setStatus(next)
            if (!next.running) {
              stopPolling()
              setReport(next.report)
              setBusy(false)
              onRefreshed()
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

    stopPolling()
    pollRef.current = setInterval(() => {
      void api.getFundamentalsRefreshStatus().then(setStatus).catch(() => {})
    }, POLL_INTERVAL_MS)

    try {
      const result = await api.refreshFundamentals()
      setReport(result)
      onRefreshed()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      stopPolling()
      setBusy(false)
      void api.getFundamentalsRefreshStatus().then(setStatus).catch(() => {})
    }
  }

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
        <div>
          <h2 style={{ marginBottom: '0.2rem' }}>{t('scores.refreshTitle')}</h2>
          <span className="muted">{t('scores.refreshSubtitle')}</span>
        </div>
        <button disabled={busy} onClick={() => void run()}>
          {busy ? t('scores.refreshing') : t('scores.refresh')}
        </button>
      </div>

      {busy && status && status.total > 0 && <ProgressBar phaseLabel={t('scores.refreshing')} status={status} />}

      {error && (
        <div className="notice error" style={{ marginTop: '1rem', marginBottom: 0 }}>
          {error}
        </div>
      )}

      {report && report.outcomes[0]?.code === 'fundamentals.alreadyRunning' && (
        <div className="notice warning" style={{ marginTop: '1rem', marginBottom: 0 }}>
          {t('fundamentals.alreadyRunning')}
        </div>
      )}

      {report && report.outcomes[0]?.code !== 'fundamentals.alreadyRunning' && (
        <div
          className={`notice ${report.failed > 0 ? 'warning' : 'info'}`}
          style={{ marginTop: '1rem', marginBottom: 0 }}
        >
          {t('scores.refreshSummary', {
            updated: report.updated,
            skipped: report.skipped,
            notApplicable: report.not_applicable,
            failed: report.failed,
          })}
        </div>
      )}
    </div>
  )
}
