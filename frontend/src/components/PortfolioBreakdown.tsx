import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BreakdownDimension, BreakdownItem } from '../api/types'
import { type TranslateParams, useI18n } from '../i18n'

const DIMENSIONS: BreakdownDimension[] = ['category', 'currency', 'country', 'sector']

//: Categorical series cap: past this, the tail folds into "Other" rather than
//: generating a 9th hue (which would be indistinguishable under CVD).
const MAX_SLICES = 8

/**
 * Portfolio value split by asset class, currency or country of listing.
 *
 * All three dimensions are already captured at import time (broker-supplied), so
 * this needs no new provider or API key — unlike a sector breakdown, which would.
 * A stacked bar rather than a pie/donut: part-to-whole is exactly the job a
 * stacked bar reads more precisely than a pie (see dataviz choosing-a-form).
 */
export function PortfolioBreakdown() {
  const { t, formatNumber } = useI18n()
  const [dimension, setDimension] = useState<BreakdownDimension>('category')
  const [items, setItems] = useState<BreakdownItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [enriching, setEnriching] = useState(false)
  const [enrichNotice, setEnrichNotice] = useState<string | null>(null)

  const load = () => {
    let cancelled = false
    setError(null)
    api
      .getBreakdown(dimension)
      .then((result) => {
        if (!cancelled) setItems(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }

  useEffect(load, [dimension])

  async function handleEnrichSectors() {
    setEnriching(true)
    setEnrichNotice(null)
    try {
      const result = await api.enrichSectors()
      setEnrichNotice(
        t('breakdown.enrichResult', {
          enriched: result.enriched,
          skipped: result.skipped,
          failed: result.failed,
        }),
      )
      load()
    } catch (err) {
      setEnrichNotice(err instanceof Error ? err.message : String(err))
    } finally {
      setEnriching(false)
    }
  }

  const slices = items ? foldTail(items) : null

  return (
    <div className="card">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '1rem',
          flexWrap: 'wrap',
          marginBottom: '0.8rem',
        }}
      >
        <h2 style={{ marginBottom: 0 }}>{t('breakdown.title')}</h2>
        <div className="form-row" style={{ marginBottom: 0 }}>
          {DIMENSIONS.map((dim) => (
            <button
              key={dim}
              className={dim === dimension ? 'primary' : undefined}
              onClick={() => setDimension(dim)}
            >
              {t(`breakdown.dimension.${dim}`)}
            </button>
          ))}
        </div>
      </div>

      {dimension === 'sector' && (
        <div style={{ marginBottom: '0.8rem' }}>
          <button onClick={() => void handleEnrichSectors()} disabled={enriching}>
            {enriching ? t('breakdown.enriching') : t('breakdown.enrichSectors')}
          </button>
          {enrichNotice && (
            <span className="muted" style={{ marginLeft: '0.6rem', fontSize: '0.82rem' }}>
              {enrichNotice}
            </span>
          )}
        </div>
      )}

      {error && <div className="notice error">{error}</div>}

      {!error && slices && slices.length === 0 && <div className="empty">{t('breakdown.empty')}</div>}

      {!error && slices && slices.length > 0 && (
        <>
          <div className="breakdown-bar" role="img" aria-label={t('breakdown.title')}>
            {slices.map((item, i) => (
              <div
                key={item.label}
                className="breakdown-segment"
                style={{ width: `${item.weight_percent}%`, background: `var(--series-${i + 1})` }}
                title={`${labelFor(item.label, dimension, t)} — ${formatNumber(item.value)} (${item.weight_percent.toFixed(1)}%)`}
              />
            ))}
          </div>

          <ul className="breakdown-legend">
            {slices.map((item, i) => (
              <li key={item.label}>
                <span className="breakdown-swatch" style={{ background: `var(--series-${i + 1})` }} />
                <span className="breakdown-label">{labelFor(item.label, dimension, t)}</span>
                <span className="breakdown-value muted">
                  {formatNumber(item.value)} · {item.weight_percent.toFixed(1)}%
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function foldTail(items: BreakdownItem[]): BreakdownItem[] {
  if (items.length <= MAX_SLICES) return items
  const head = items.slice(0, MAX_SLICES - 1)
  const tail = items.slice(MAX_SLICES - 1)
  return [
    ...head,
    {
      label: 'OTHER',
      value: tail.reduce((sum, i) => sum + i.value, 0),
      weight_percent: tail.reduce((sum, i) => sum + i.weight_percent, 0),
    },
  ]
}

function labelFor(
  label: string,
  dimension: BreakdownDimension,
  t: (key: string, params?: TranslateParams) => string,
): string {
  if (label === 'UNKNOWN') return t('breakdown.unknown')
  if (label === 'OTHER') return t('breakdown.other')
  if (dimension === 'category') {
    // STOCK / ETF / CFD-style broker codes: translate if we have a label for it,
    // otherwise show the raw code rather than hiding it.
    const key = `breakdown.category.${label}`
    const translated = t(key)
    return translated === key ? label : translated
  }
  return label
}
