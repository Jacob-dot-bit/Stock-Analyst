import type { MetricScore, Score } from '../api/types'
import { scoreBand } from './ScoreBadge'
import { useI18n } from '../i18n'

const PILLAR_ORDER = ['value', 'growth', 'quality', 'technical']

/** Metrics whose raw value is a fraction meant to be read as a percentage
 * (a growth rate, a yield, a price-vs-average gap) — shown as "7.2%", not
 * the confusing raw decimal "0.072" a user would otherwise have to convert
 * in their head. Can go negative (a decline, a price below its average), so
 * these keep the +/- sign. Ratios that aren't percentages at all (P/E, P/B,
 * Debt/Equity) are deliberately excluded — those are conventionally read as
 * plain numbers, not percentages. */
const SIGNED_PERCENT_METRICS = new Set([
  'fcf_yield',
  'revenue_cagr',
  'net_income_cagr',
  'price_vs_sma200',
  'momentum_12_1',
  'sma50_vs_sma200',
])

/** Also a percentage, but structurally never negative (a share of years with
 * positive growth, or a dividend yield) — a "+" prefix would be redundant,
 * not just unsigned. */
const PLAIN_PERCENT_METRICS = new Set(['revenue_growth_consistency', 'dividend_yield'])

/** The Quality pillar's Piotroski-style pass/fail checks (`kind: binary` in
 * scoring.yaml) — their raw value is 1.0/0.0, not a quantity, so printing it
 * through `formatNumber` read as a bare "1" or "0" with no indication that
 * was a pass/fail result rather than a truncated real number. */
const BINARY_METRICS = new Set([
  'roa_positive',
  'cfo_positive',
  'accruals_quality',
  'leverage_not_increasing',
  'no_significant_dilution',
])

/** The full per-metric breakdown behind one instrument's composite score —
 * extracted so both the standalone table row below (Watchlist/Screener) and
 * the consolidated per-position detail panel (`PositionDetailRow.tsx`) can
 * render the exact same content without duplicating it. See DEVLOG
 * "Decision 3r.1" and "Decision 3u.31". */
export function ScoreBreakdown({ score }: { score: Score }) {
  const { t, formatNumber, formatSignedPercent } = useI18n()

  const pillars = [...score.pillars].sort(
    (a, b) => PILLAR_ORDER.indexOf(a.name) - PILLAR_ORDER.indexOf(b.name),
  )

  // Same 66/33 thresholds as `scoreBand`, applied per metric rather than to
  // the composite — a metric strictly between the two is neither a
  // strength nor a watch-point, just unremarkable, and stays out of both
  // lists rather than being forced into one.
  const allMetrics: MetricScore[] = pillars.flatMap((p) => p.metrics)
  const strengths = allMetrics.filter((m) => scoreBand(m.score) === 'high')
  const watchPoints = allMetrics.filter((m) => scoreBand(m.score) === 'low')

  function formatMetricValue(metricName: string, value: number | null): string {
    if (value === null) return '—'
    if (SIGNED_PERCENT_METRICS.has(metricName)) return formatSignedPercent(value * 100)
    if (PLAIN_PERCENT_METRICS.has(metricName)) return `${formatNumber(value * 100, 1)}%`
    if (BINARY_METRICS.has(metricName)) return t(value === 1 ? 'scores.binaryPass' : 'scores.binaryFail')
    return formatNumber(value, 3)
  }

  const band = scoreBand(score.composite)

  return (
        <div className="score-detail">
          <div className="score-summary">
            <p className="score-summary-sentence">
              {t('scores.summarySentence', {
                score: formatNumber(score.composite, 0),
                band: band !== 'none' ? t(`scores.summary.${band}`) : '',
              })}
            </p>
            <div className="score-summary-lists">
              <div className="score-summary-list">
                <strong>{t('scores.strengths')}</strong>
                {strengths.length > 0 ? (
                  <ul>
                    {strengths.map((m) => (
                      <li key={m.name}>{t(`scores.metric.${m.name}`)}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="muted">{t('scores.noneIdentified')}</span>
                )}
              </div>
              <div className="score-summary-list">
                <strong>{t('scores.watchPoints')}</strong>
                {watchPoints.length > 0 ? (
                  <ul>
                    {watchPoints.map((m) => (
                      <li key={m.name}>{t(`scores.metric.${m.name}`)}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="muted">{t('scores.noneIdentified')}</span>
                )}
              </div>
            </div>
          </div>
          {pillars.map((pillar) => (
            <div key={pillar.name} className="score-detail-pillar">
              <div className="score-detail-pillar-header">
                <strong>{t(`scores.pillar.${pillar.name}`)}</strong>
                <span className={pillar.score === null ? 'muted' : ''}>
                  {pillar.score !== null
                    ? t('scores.pillarScore', {
                        score: formatNumber(pillar.score, 0),
                        weight: formatNumber(pillar.weight_used, 0),
                      })
                    : t('scores.pillarDropped')}
                </span>
              </div>
              <table className="score-detail-metrics">
                <tbody>
                  {pillar.metrics.map((metric) => (
                    <tr key={metric.name}>
                      <td>{t(`scores.metric.${metric.name}`)}</td>
                      <td className="num">{formatMetricValue(metric.name, metric.value)}</td>
                      <td className="num">{metric.score !== null ? formatNumber(metric.score, 0) : '—'}</td>
                      <td className="muted score-detail-reason">
                        {metric.dropped_reason ? t(`scores.droppedReason.${metric.dropped_reason}`) : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
  )
}

/** Standalone table row wrapping `ScoreBreakdown` — no modal/portal exists
 * in this codebase to reuse, so this stays a plain extra `<tr>` like the
 * rest of the table. Used by Watchlist/Screener; `PositionsTable` embeds
 * `ScoreBreakdown` directly inside its consolidated detail panel instead. */
export function ScoreDetailRow({ score, colSpan }: { score: Score; colSpan: number }) {
  return (
    <tr className="score-detail-row">
      <td colSpan={colSpan}>
        <ScoreBreakdown score={score} />
      </td>
    </tr>
  )
}
