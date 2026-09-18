import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Portfolio, QuoteStatus, RefreshReport, RefreshStatus } from '../api/types'
import { ProgressBar } from './ProgressBar'
import { useI18n } from '../i18n'

interface Props {
  //: Cache-only portfolio + sparklines reload — used for the retry-failed path,
  //: which only touches the history phase and so has no fresh live result to
  //: hand back directly.
  onRefreshed: () => void
  //: Called with the full, already-recomputed portfolio once the live-quote
  //: phase completes — the caller replaces its state directly rather than
  //: issuing a second GET, since live quotes are never persisted (see
  //: `prices/quote_service.py`'s module docstring) and a plain reload would
  //: silently lose whatever this round just fetched.
  onLivePortfolio: (portfolio: Portfolio) => void
}

const POLL_INTERVAL_MS = 800

//: Outcome codes worth an immediate retry — transient or throttling failures.
//: Deliberately excludes codes that need a user fix first (needsIsin, notMapped,
//: planLimited, noProvider): retrying those would just fail the same way again.
const RETRYABLE_CODES = new Set([
  'prices.rateLimited',
  'prices.symbolNotFound',
  'prices.stillUnavailable',
  'prices.failed',
])

type Phase = 'history' | 'live'

/**
 * Triggers a full price update and reports, per instrument, what happened.
 *
 * One button, two budgeted phases run back to back: first the daily-bar history
 * (feeds the trend charts), then a live-quote round that recomputes the whole
 * portfolio — market value, unrealised P&L, performance, per position — with
 * whatever fresher pricing it found. These used to be three separate controls,
 * one of them a redundant "Recalculer" (DEVLOG "Decision 2f.1"), then two
 * ("Rafraîchir les cours" / "Prix frais" on a now-removed secondary "Valeur
 * actuelle estimée" card — "Decision 2f.2"), then finally merged into the
 * portfolio's own primary totals instead of a second, competing number
 * ("Decision 2f.3"). A "retry failed" round only redoes phase 1 for the given
 * symbols — phase 2 always covers the whole portfolio, so redoing it for a
 * handful of retried symbols would spend the full live-quote budget for no
 * reason.
 *
 * Free providers rate-limit hard — Yahoo returned 429 after four rapid requests — so
 * each phase works through its list within a time budget and says how many instruments
 * are left. A *simulated* progress bar over that would be dishonest, which is why this
 * used to show nothing while the request was in flight — but the actual instrument count
 * is known and tracked server-side, polled here while the triggering request is still
 * running. The bar reflects real, already-settled instruments, never a guess.
 */
export function RefreshPanel({ onRefreshed, onLivePortfolio }: Props) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState<Phase | null>(null)
  const [report, setReport] = useState<RefreshReport | null>(null)
  const [historyStatus, setHistoryStatus] = useState<RefreshStatus | null>(null)
  const [liveStatus, setLiveStatus] = useState<QuoteStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPolling() {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  // Progress lives server-side (both status endpoints are process-wide, not
  // tied to any one request), but `busy`/`phase` here are local component
  // state — so navigating away mid-refresh and back used to remount this
  // panel with a blank slate while the backend kept working, making the bar
  // vanish even though nothing had actually stopped. On mount, check both
  // phases once: if either is still running, resume showing it instead of
  // assuming idle.
  //
  // One real limit this can't paper over: phase 2's priced result only ever
  // existed in the direct POST response body of whichever call started it —
  // `QuoteStatusOut` carries progress, not the portfolio it produced. A round
  // that finishes while unmounted still gets its fresh quotes computed and
  // spent from the provider's quota, but nothing keeps that specific result
  // around to hand back to a panel that resumes observing it after the fact;
  // the best this can do is fall back to a cache-only reload once it ends,
  // same as the retry path already does.
  useEffect(() => {
    let cancelled = false

    async function resume() {
      const [history, live] = await Promise.all([
        api.getRefreshStatus().catch(() => null),
        api.getRefreshLiveStatus().catch(() => null),
      ])
      if (cancelled) return

      if (history?.running) {
        setBusy(true)
        setPhase('history')
        setHistoryStatus(history)
        pollRef.current = setInterval(() => {
          void api
            .getRefreshStatus()
            .then((status) => {
              setHistoryStatus(status)
              if (!status.running) {
                stopPolling()
                setReport(status.report)
                setBusy(false)
                setPhase(null)
                onRefreshed()
              }
            })
            .catch(() => {})
        }, POLL_INTERVAL_MS)
      } else if (live?.running) {
        setBusy(true)
        setPhase('live')
        setLiveStatus(live)
        pollRef.current = setInterval(() => {
          void api
            .getRefreshLiveStatus()
            .then((status) => {
              setLiveStatus(status)
              if (!status.running) {
                stopPolling()
                setBusy(false)
                setPhase(null)
                onRefreshed()
              }
            })
            .catch(() => {})
        }, POLL_INTERVAL_MS)
      }
    }

    void resume()
    return () => {
      cancelled = true
      stopPolling()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only resume check
  }, [])

  async function run(symbols?: string[]) {
    setBusy(true)
    setError(null)
    setHistoryStatus(null)
    setLiveStatus(null)

    setPhase('history')
    stopPolling()
    pollRef.current = setInterval(() => {
      void api.getRefreshStatus().then(setHistoryStatus).catch(() => {})
    }, POLL_INTERVAL_MS)

    try {
      const isRetry = Boolean(symbols)
      // A targeted retry forces the fetch: those symbols were already asked today
      // (that is why they show up as failed), so without `force` the daily gate
      // would just report "already checked" without trying again.
      const historyResult = await api.refreshPrices(isRetry, symbols)
      setReport(historyResult)
      stopPolling()
      void api.getRefreshStatus().then(setHistoryStatus).catch(() => {})

      if (isRetry) {
        // A retry is scoped to the failed symbols only — the live-quote phase
        // has no such scoping and always covers every holding, so re-running
        // it here would just burn the full budget again for no new coverage.
        onRefreshed()
        return
      }

      setPhase('live')
      pollRef.current = setInterval(() => {
        void api.getRefreshLiveStatus().then(setLiveStatus).catch(() => {})
      }, POLL_INTERVAL_MS)

      const portfolio = await api.refreshLivePrices()
      onLivePortfolio(portfolio)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      stopPolling()
      setPhase(null)
      setBusy(false)
      void api.getRefreshLiveStatus().then(setLiveStatus).catch(() => {})
    }
  }

  const retryableSymbols = report
    ? [
        ...new Set(
          report.outcomes
            .filter((o) => RETRYABLE_CODES.has(o.code))
            .map((o) => o.params.symbol)
            .filter((s): s is string => typeof s === 'string'),
        ),
      ]
    : []

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
        <div>
          <h2 className="compact">{t('prices.title')}</h2>
          <span className="muted">{t('prices.subtitle')}</span>
        </div>
        <button className="primary" disabled={busy} onClick={() => void run()}>
          {busy ? t('prices.refreshing') : t('prices.refresh')}
        </button>
      </div>

      {busy && phase === 'history' && historyStatus && historyStatus.total > 0 && (
        <ProgressBar phaseLabel={t('prices.phaseHistory')} status={historyStatus} />
      )}
      {busy && phase === 'live' && liveStatus && liveStatus.total > 0 && (
        <ProgressBar phaseLabel={t('prices.phaseLive')} status={liveStatus} />
      )}

      {error && (
        <div className="notice error" style={{ marginTop: '1rem', marginBottom: 0 }}>
          {error}
        </div>
      )}

      {report && <RefreshResult report={report} />}

      {!busy && retryableSymbols.length > 0 && (
        <button
          style={{ marginTop: '0.8rem' }}
          onClick={() => void run(retryableSymbols)}
        >
          {t('prices.retryFailed', { count: retryableSymbols.length })}
        </button>
      )}
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
