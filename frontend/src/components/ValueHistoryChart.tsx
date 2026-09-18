import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { ValueHistory, ValueHistoryPoint } from '../api/types'
import { useI18n } from '../i18n'

const WIDTH = 640
const HEIGHT = 220
const PADDING = { top: 12, right: 12, bottom: 26, left: 56 }
const Y_TICKS = 4
const X_TICKS = 5

interface ChartGeometry {
  valueLine: string
  investedLine: string
  benchmarkLine: string
  yTicks: { value: number; y: number }[]
  xTicks: { date: string; x: number }[]
}

/**
 * Real historical portfolio value, replaying actual buys/sells from the `Lot`
 * ledger — not a backtest of today's holdings (see DEVLOG "Decision 3b.1").
 * Value and cost basis (invested) share one Y axis on purpose: normalising
 * them independently would make the visual comparison between the two
 * meaningless.
 *
 * No chart library, same reasoning as Sparkline.tsx: two polylines and a
 * couple of axes are not worth a dependency this app has never needed
 * elsewhere. No hover/tooltip for v1 — precise numbers live in the cards
 * above, not here. Tight min/max scaling (not zero-anchored), matching
 * Sparkline's own convention, since the point is the shape of the trend.
 */
export function ValueHistoryChart() {
  const { t, formatNumber, formatDate } = useI18n()
  const [history, setHistory] = useState<ValueHistory | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getValueHistory()
      .then((result) => {
        if (!cancelled) setHistory(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const geometry = useMemo(
    () => (history && history.points.length > 0 ? buildChart(history.points) : null),
    [history],
  )

  if (error) {
    return (
      <div className="card">
        <h2>{t('history.title')}</h2>
        <div className="notice error">{error}</div>
      </div>
    )
  }

  if (!history) return null // still loading

  if (history.points.length === 0) {
    return (
      <div className="card">
        <h2>{t('history.title')}</h2>
        <div className="empty">{t('history.empty')}</div>
      </div>
    )
  }

  return (
    <div className="card">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          flexWrap: 'wrap',
          gap: '0.5rem',
        }}
      >
        <h2 className="compact">{t('history.title')}</h2>
        <div style={{ display: 'flex', gap: '1rem', fontSize: '0.82rem' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
            <span className="breakdown-swatch" style={{ background: 'var(--series-1)' }} />
            {t('history.value')}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
            <span className="breakdown-swatch" style={{ background: 'var(--series-2)' }} />
            {t('history.invested')}
          </span>
          {history.benchmark_available && (
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <span className="breakdown-swatch" style={{ background: 'var(--series-3)' }} />
              {history.benchmark_name ?? t('history.benchmark')}
            </span>
          )}
        </div>
      </div>

      {geometry && (
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={t('history.title')}
          style={{ width: '100%', height: 'auto', marginTop: '0.6rem', overflow: 'visible' }}
        >
          {geometry.yTicks.map((tick) => (
            <g key={tick.value}>
              <line
                x1={PADDING.left}
                x2={WIDTH - PADDING.right}
                y1={tick.y}
                y2={tick.y}
                stroke="var(--border)"
                strokeWidth="1"
              />
              <text
                x={PADDING.left - 8}
                y={tick.y}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize="10"
                fill="var(--text-muted)"
              >
                {formatNumber(tick.value, 0)}
              </text>
            </g>
          ))}

          {geometry.xTicks.map((tick) => (
            <text
              key={tick.date}
              x={tick.x}
              y={HEIGHT - PADDING.bottom + 16}
              textAnchor="middle"
              fontSize="10"
              fill="var(--text-muted)"
            >
              {formatDate(tick.date)}
            </text>
          ))}

          {geometry.investedLine && (
            <polyline points={geometry.investedLine} fill="none" stroke="var(--series-2)" strokeWidth="1.5" />
          )}
          {history.benchmark_available && geometry.benchmarkLine && (
            <polyline
              points={geometry.benchmarkLine}
              fill="none"
              stroke="var(--series-3)"
              strokeWidth="1.5"
              strokeDasharray="4 2"
            />
          )}
          {geometry.valueLine && (
            <polyline points={geometry.valueLine} fill="none" stroke="var(--series-1)" strokeWidth="2" />
          )}
        </svg>
      )}

      <div className="muted" style={{ marginTop: '0.6rem', fontSize: '0.78rem' }}>
        {t('history.caveat')}
      </div>

      {history.benchmark_available && (
        <div className="muted" style={{ marginTop: '0.3rem', fontSize: '0.78rem' }}>
          {t('history.benchmarkCaveat')}
        </div>
      )}

      {history.capped_by_history && history.start_date && (
        <div className="muted" style={{ marginTop: '0.3rem', fontSize: '0.78rem' }}>
          {t('history.capped', { date: formatDate(history.start_date) })}
        </div>
      )}
    </div>
  )
}

function buildChart(points: ValueHistoryPoint[]): ChartGeometry | null {
  const allValues = points
    .flatMap((p) => [p.value, p.invested, p.benchmark])
    .filter((v): v is number => v !== null)
  if (allValues.length === 0) return null

  const rawMin = Math.min(...allValues)
  const rawMax = Math.max(...allValues)
  const rawSpan = rawMax - rawMin || Math.abs(rawMax) || 1
  // A little breathing room so the lines never sit flush against the top/bottom
  // gridline.
  const min = rawMin - rawSpan * 0.05
  const max = rawMax + rawSpan * 0.05
  const span = max - min || 1

  const innerWidth = WIDTH - PADDING.left - PADDING.right
  const innerHeight = HEIGHT - PADDING.top - PADDING.bottom
  const lastIndex = Math.max(1, points.length - 1)

  const x = (index: number) => PADDING.left + (index / lastIndex) * innerWidth
  const y = (value: number) => PADDING.top + innerHeight - ((value - min) / span) * innerHeight

  const toPolyline = (key: 'value' | 'invested' | 'benchmark') =>
    points
      .map((p, i) => {
        const raw = p[key]
        return raw === null ? null : `${x(i).toFixed(1)},${y(raw).toFixed(1)}`
      })
      .filter((s): s is string => s !== null)
      .join(' ')

  const yTicks = Array.from({ length: Y_TICKS + 1 }, (_, i) => {
    const value = min + (span * i) / Y_TICKS
    return { value, y: y(value) }
  })

  const xTickCount = Math.min(X_TICKS, points.length)
  const xLastIndex = Math.max(1, xTickCount - 1)
  const xTicks = Array.from({ length: xTickCount }, (_, i) => {
    const index = Math.round((i / xLastIndex) * (points.length - 1))
    return { date: points[index].date, x: x(index) }
  })

  return {
    valueLine: toPolyline('value'),
    investedLine: toPolyline('invested'),
    benchmarkLine: toPolyline('benchmark'),
    yTicks,
    xTicks,
  }
}
