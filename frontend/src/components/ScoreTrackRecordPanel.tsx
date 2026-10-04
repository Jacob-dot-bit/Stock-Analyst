import { useState } from 'react'
import { api } from '../api/client'
import type { ScoreBacktest, ScoreBacktestUniverse } from '../api/types'
import { useI18n } from '../i18n'

/** Below either threshold the result is shown, but flagged as too thin to
 * read anything into — a handful of instruments or dates proves nothing. */
const MIN_PERIODS = 12
const MIN_INSTRUMENTS = 20

/**
 * The composite score's own track record: on each past month, the score is
 * recomputed with only the data known at the time (`app/backtest/service.py`),
 * instruments are split into quartiles, and their forward returns compared.
 * An aggregate report, never a per-instrument promise.
 */
export function ScoreTrackRecordPanel() {
  const { t, formatNumber, formatSignedPercent, formatDate } = useI18n()
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<ScoreBacktest | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [universe, setUniverse] = useState<ScoreBacktestUniverse>('mine')

  async function run() {
    setBusy(true)
    setError(null)
    try {
      setReport(await api.runScoreBacktest(universe))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const pct = (value: number | null) => (value === null ? '—' : formatSignedPercent(value * 100))
  const definedPeriods = report ? report.periods.filter((p) => p.spread !== null) : []
  const thin = report !== null && (definedPeriods.length < MIN_PERIODS || report.instruments_scored < MIN_INSTRUMENTS)

  return (
    <div className="card">
      <h2 style={{ marginBottom: '0.2rem' }}>{t('scoreTrack.title')}</h2>
      <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
        {t('scoreTrack.description')}
      </p>
      <div className="form-row">
        <label>
          {t('scoreTrack.universe')}{' '}
          <select value={universe} onChange={(e) => setUniverse(e.target.value as ScoreBacktestUniverse)}>
            <option value="mine">{t('scoreTrack.universeMine')}</option>
            <option value="wide">{t('scoreTrack.universeWide')}</option>
          </select>
        </label>
        <button disabled={busy} onClick={() => void run()}>
          {busy ? t('scoreTrack.running') : t('scoreTrack.run')}
        </button>
      </div>

      {error && (
        <div className="notice error" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          {error}
        </div>
      )}

      {report && report.observations === 0 && (
        <div className="empty" style={{ marginTop: '0.8rem' }}>
          {t('scoreTrack.empty')}
        </div>
      )}

      {report && report.observations > 0 && (
        <div style={{ marginTop: '0.8rem' }}>
          <div className="notice warning" style={{ marginBottom: '0.8rem' }}>
            {t(report.universe === 'wide' ? 'scoreTrack.disclaimerWide' : 'scoreTrack.disclaimer')}
          </div>

          <dl className="position-detail-facts">
            <div>
              <dt>{t('scoreTrack.window')}</dt>
              <dd>
                {formatDate(report.start)} → {formatDate(report.end)}
              </dd>
            </div>
            <div>
              <dt>{t('scoreTrack.horizon')}</dt>
              <dd>{t('scoreTrack.months', { count: report.horizon_months })}</dd>
            </div>
            <div>
              <dt>{t('scoreTrack.instruments')}</dt>
              <dd>{formatNumber(report.instruments_scored, 0)}</dd>
            </div>
            <div>
              <dt>{t('scoreTrack.spread')}</dt>
              <dd>{pct(report.top_minus_bottom)}</dd>
            </div>
            <div>
              <dt>{t('scoreTrack.hitRate')}</dt>
              <dd>
                {report.hit_rate === null ? '—' : `${formatNumber(report.hit_rate * 100, 0)}%`} (
                {formatNumber(definedPeriods.length, 0)})
              </dd>
            </div>
          </dl>

          {thin && (
            <div className="notice warning" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
              {t('scoreTrack.thinWarning')}
            </div>
          )}

          <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
            <table>
              <thead>
                <tr>
                  <th>{t('scoreTrack.quartile')}</th>
                  <th className="num">{t('scoreTrack.count')}</th>
                  <th className="num">{t('scoreTrack.meanReturn')}</th>
                  <th className="num">{t('scoreTrack.medianReturn')}</th>
                </tr>
              </thead>
              <tbody>
                {[...report.buckets].reverse().map((bucket) => (
                  <tr key={bucket.quartile}>
                    <td>{t(`scoreTrack.q${bucket.quartile}`)}</td>
                    <td className="num">{formatNumber(bucket.count, 0)}</td>
                    <td className="num">{pct(bucket.mean_return)}</td>
                    <td className="num">{pct(bucket.median_return)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {definedPeriods.length > 0 && (
            <SpreadBars
              periods={definedPeriods}
              label={t('scoreTrack.perPeriod')}
              dateHeader={t('scoreTrack.month')}
              spreadHeader={t('scoreTrack.spread')}
              formatDate={formatDate}
              formatSpread={pct}
            />
          )}
        </div>
      )}
    </div>
  )
}

/** One bar per rebalance date: above the line when the top quartile beat the
 * bottom one, below when it lagged — shows whether the average is steady or
 * carried by a few months. The same values are in a visually hidden table,
 * since the bars themselves are invisible to screen readers. */
function SpreadBars({
  periods,
  label,
  dateHeader,
  spreadHeader,
  formatDate,
  formatSpread,
}: {
  periods: ScoreBacktest['periods']
  label: string
  dateHeader: string
  spreadHeader: string
  formatDate: (value: string) => string
  formatSpread: (value: number | null) => string
}) {
  const width = 600
  const height = 80
  const max = Math.max(...periods.map((p) => Math.abs(p.spread ?? 0)), 1e-9)
  const step = width / periods.length
  const mid = height / 2
  return (
    <figure style={{ margin: '0.8rem 0 0' }}>
      <figcaption className="muted" style={{ fontSize: '0.8rem', marginBottom: '0.3rem' }}>
        {label}
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none" aria-hidden="true">
        <line x1={0} x2={width} y1={mid} y2={mid} stroke="var(--border-strong)" strokeWidth={1} />
        {periods.map((p, i) => {
          const spread = p.spread ?? 0
          const h = (Math.abs(spread) / max) * (mid - 2)
          return (
            <rect
              key={p.rebalance_date}
              x={i * step + step * 0.15}
              width={Math.max(step * 0.7, 1)}
              y={spread >= 0 ? mid - h : mid}
              height={h}
              fill={spread >= 0 ? 'var(--positive)' : 'var(--negative)'}
            >
              <title>{`${formatDate(p.rebalance_date)}: ${formatSpread(p.spread)}`}</title>
            </rect>
          )
        })}
      </svg>
      <table className="visually-hidden">
        <caption>{label}</caption>
        <thead>
          <tr>
            <th scope="col">{dateHeader}</th>
            <th scope="col">{spreadHeader}</th>
          </tr>
        </thead>
        <tbody>
          {periods.map((p) => (
            <tr key={p.rebalance_date}>
              <td>{formatDate(p.rebalance_date)}</td>
              <td>{formatSpread(p.spread)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
