import { useEffect, useMemo, useState } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'
import { api } from '../api/client'
import type { ValueHistory, ValueHistoryPoint } from '../api/types'
import { useElementWidth } from '../hooks/useElementWidth'
import { useI18n } from '../i18n'

const HEIGHT = 240
const PADDING = { top: 16, right: 12, bottom: 28, left: 64 }
const Y_TICKS = 4
// One date label per ~110px keeps the labels from colliding on a phone
// while still giving a wide screen more than a handful of anchors.
const X_TICK_SPACING = 110
const MIN_POINTS = 2

interface ChartGeometry {
  valueLine: string
  investedLine: string
  benchmarkLine: string
  yTicks: { value: number; y: number }[]
  xTicks: { date: string; x: number }[]
  x: (index: number) => number
  y: (value: number) => number
}

type SeriesKey = 'value' | 'invested' | 'benchmark'

/**
 * Real historical portfolio value, replaying actual buys/sells from the `Lot`
 * ledger — not a backtest of today's holdings (see DEVLOG "Decision 3b.1").
 * Value and cost basis (invested) share one Y axis on purpose: normalising
 * them independently would make the visual comparison between the two
 * meaningless.
 *
 * No chart library, same reasoning as Sparkline.tsx: two polylines and a
 * couple of axes are not worth a dependency this app has never needed
 * elsewhere. Hovering (or arrow keys once
 * focused) reads off the exact figures for one day. Tight min/max scaling (not zero-anchored), matching
 * Sparkline's own convention, since the point is the shape of the trend.
 */
export function ValueHistoryChart() {
  const { t, formatNumber, formatDate } = useI18n()
  const [history, setHistory] = useState<ValueHistory | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [plotRef, width] = useElementWidth<HTMLDivElement>()
  const [activeIndex, setActiveIndex] = useState<number | null>(null)

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
    () =>
      history && history.points.length >= MIN_POINTS && width > 0
        ? buildChart(history.points, width)
        : null,
    [history, width],
  )

  if (error) {
    return (
      <div className="card">
        <h2>{t('history.title')}</h2>
        <div className="notice error">{error}</div>
      </div>
    )
  }

  if (!history) {
    return (
      <div className="card" aria-busy="true">
        <h2>{t('history.title')}</h2>
        <div className="skeleton skeleton-chart" />
      </div>
    )
  }

  if (history.points.length === 0) {
    return (
      <div className="card">
        <h2>{t('history.title')}</h2>
        <div className="empty">{t('history.empty')}</div>
      </div>
    )
  }

  // A single day draws no line at all — just an empty grid that reads as
  // broken. Say so instead.
  if (history.points.length < MIN_POINTS) {
    return (
      <div className="card">
        <h2>{t('history.title')}</h2>
        <div className="empty">{t('history.tooFew')}</div>
      </div>
    )
  }

  const points = history.points
  const showBenchmark = history.benchmark_available
  const active = activeIndex !== null ? points[activeIndex] : null

  const indexFromPointer = (event: PointerEvent<SVGSVGElement>) => {
    if (!geometry) return null
    const box = event.currentTarget.getBoundingClientRect()
    const innerWidth = width - PADDING.left - PADDING.right
    const ratio = (event.clientX - box.left - PADDING.left) / innerWidth
    return Math.min(points.length - 1, Math.max(0, Math.round(ratio * (points.length - 1))))
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const last = points.length - 1
    const current = activeIndex ?? last
    let next: number | null = null
    if (event.key === 'ArrowLeft') next = Math.max(0, current - 1)
    else if (event.key === 'ArrowRight') next = Math.min(last, current + 1)
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = last
    else if (event.key === 'Escape') {
      setActiveIndex(null)
      return
    }
    if (next === null) return
    event.preventDefault()
    setActiveIndex(next)
  }

  const series: { key: SeriesKey; label: string; color: string }[] = [
    { key: 'value', label: t('history.value'), color: 'var(--series-1)' },
    { key: 'invested', label: t('history.invested'), color: 'var(--series-2)' },
    ...(showBenchmark
      ? [
          {
            key: 'benchmark' as const,
            label: history.benchmark_name ?? t('history.benchmark'),
            color: 'var(--series-3)',
          },
        ]
      : []),
  ]

  const activeX = geometry && activeIndex !== null ? geometry.x(activeIndex) : null
  // Flip the tooltip to the left of the crosshair past the middle, so it
  // never runs off the right edge.
  const tooltipOnLeft = activeX !== null && activeX > width / 2

  return (
    <div className="card">
      <div className="chart-header">
        <h2 className="compact">{t('history.title')}</h2>
        <div className="chart-legend">
          {series.map((s) => (
            <span key={s.key} className="chart-legend-item">
              <span className="breakdown-swatch" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      </div>

      <div
        ref={plotRef}
        className="chart-plot"
        tabIndex={0}
        role="group"
        aria-label={t('history.chartLabel', {
          from: formatDate(points[0].date),
          to: formatDate(points[points.length - 1].date),
        })}
        onKeyDown={onKeyDown}
        onBlur={() => setActiveIndex(null)}
      >
        {geometry && (
          <svg
            width={width}
            height={HEIGHT}
            aria-hidden="true"
            onPointerMove={(event) => setActiveIndex(indexFromPointer(event))}
            onPointerLeave={() => setActiveIndex(null)}
          >
            {geometry.yTicks.map((tick) => (
              <g key={tick.value}>
                <line
                  x1={PADDING.left}
                  x2={width - PADDING.right}
                  y1={tick.y}
                  y2={tick.y}
                  stroke="var(--border)"
                  strokeWidth="1"
                />
                <text x={PADDING.left - 8} y={tick.y} textAnchor="end" dominantBaseline="middle" className="chart-axis-label">
                  {formatNumber(tick.value, 0)}
                </text>
              </g>
            ))}

            {geometry.xTicks.map((tick, i) => (
              <text
                key={tick.date}
                x={tick.x}
                y={HEIGHT - PADDING.bottom + 18}
                textAnchor={i === 0 ? 'start' : i === geometry.xTicks.length - 1 ? 'end' : 'middle'}
                className="chart-axis-label"
              >
                {formatDate(tick.date)}
              </text>
            ))}

            {geometry.investedLine && (
              <polyline points={geometry.investedLine} fill="none" stroke="var(--series-2)" strokeWidth="1.5" />
            )}
            {showBenchmark && geometry.benchmarkLine && (
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

            {active && activeX !== null && (
              <g>
                <line
                  x1={activeX}
                  x2={activeX}
                  y1={PADDING.top}
                  y2={HEIGHT - PADDING.bottom}
                  stroke="var(--border-strong)"
                  strokeWidth="1"
                />
                {series.map((s) => {
                  const raw = active[s.key]
                  return raw === null ? null : (
                    <circle
                      key={s.key}
                      cx={activeX}
                      cy={geometry.y(raw)}
                      r="4"
                      fill={s.color}
                      stroke="var(--surface)"
                      strokeWidth="2"
                    />
                  )
                })}
              </g>
            )}
          </svg>
        )}

        {active && activeX !== null && (
          <div
            className="chart-tooltip"
            style={
              tooltipOnLeft
                ? { right: width - activeX + 12, top: PADDING.top }
                : { left: activeX + 12, top: PADDING.top }
            }
          >
            <div className="chart-tooltip-date">{formatDate(active.date)}</div>
            {series.map((s) => (
              <div key={s.key} className="chart-tooltip-row">
                <span className="breakdown-swatch" style={{ background: s.color }} />
                <span>{s.label}</span>
                <span className="chart-tooltip-value">
                  {active[s.key] === null ? t('common.none') : formatNumber(active[s.key], 2)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Announces the day the arrow keys landed on; the visual tooltip
          alone is invisible to a screen reader. */}
      <div className="visually-hidden" aria-live="polite">
        {active
          ? `${formatDate(active.date)}: ${series
              .map((s) => `${s.label} ${active[s.key] === null ? t('common.none') : formatNumber(active[s.key], 2)}`)
              .join(', ')}`
          : ''}
      </div>

      <p className="chart-note">{t('history.caveat')}</p>
      {showBenchmark && <p className="chart-note">{t('history.benchmarkCaveat')}</p>}
      {history.capped_by_history && history.start_date && (
        <p className="chart-note">{t('history.capped', { date: formatDate(history.start_date) })}</p>
      )}
    </div>
  )
}

function buildChart(points: ValueHistoryPoint[], width: number): ChartGeometry | null {
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

  const innerWidth = Math.max(1, width - PADDING.left - PADDING.right)
  const innerHeight = HEIGHT - PADDING.top - PADDING.bottom
  const lastIndex = Math.max(1, points.length - 1)

  const x = (index: number) => PADDING.left + (index / lastIndex) * innerWidth
  const y = (value: number) => PADDING.top + innerHeight - ((value - min) / span) * innerHeight

  const toPolyline = (key: SeriesKey) =>
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

  const xTickCount = Math.max(2, Math.min(points.length, Math.floor(innerWidth / X_TICK_SPACING) + 1))
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
    x,
    y,
  }
}
