import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { AttentionItem } from '../api/types'
import { useI18n, type TranslateParams } from '../i18n'

function categoryLabel(category: string, t: (key: string) => string): string {
  if (category === 'UNKNOWN') return t('breakdown.unknown')
  const key = `breakdown.category.${category}`
  const translated = t(key)
  return translated === key ? category : translated
}

function itemText(
  item: AttentionItem,
  t: (key: string, params?: TranslateParams) => string,
  formatNumber: (value: number | null | undefined, digits?: number) => string,
): string {
  switch (item.kind) {
    case 'unresolved_instruments':
      return t('attention.unresolvedInstruments', { count: item.count })
    case 'price_error':
      return t('attention.priceError', { count: item.count })
    case 'price_stale':
      return t('attention.priceStale', { count: item.count })
    case 'allocation_under':
      return t('attention.allocationUnder', {
        category: categoryLabel(item.category ?? '', t),
        gap: formatNumber(item.gap_pct, 1),
      })
    case 'allocation_over':
      return t('attention.allocationOver', {
        category: categoryLabel(item.category ?? '', t),
        gap: formatNumber(item.gap_pct, 1),
      })
  }
}

/**
 * A short, ranked list of facts worth checking today — the first thing shown
 * on the Portfolio page, before the detailed tables. Purely descriptive:
 * every item names something already true (stale price, unresolved symbol,
 * allocation gap), never a suggestion to buy or sell. See DEVLOG "Decision
 * 3u.25". Self-contained, same fetch-on-mount pattern as `AllocationTargets`.
 */
export function AttentionCard() {
  const { t, formatNumber } = useI18n()
  const [items, setItems] = useState<AttentionItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getAttention()
      .then(setItems)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  if (error || items === null) return null

  return (
    <div className="card">
      <h2>{t('attention.title')}</h2>
      {items.length === 0 ? (
        <p className="muted" style={{ marginTop: 0 }}>
          {t('attention.allClear')}
        </p>
      ) : (
        <ul className="attention-list">
          {items.map((item, i) => (
            <li key={i} className={`attention-item ${item.severity}`}>
              {item.kind === 'unresolved_instruments' ? (
                <Link to="/settings#integrite-corrections">{itemText(item, t, formatNumber)}</Link>
              ) : (
                itemText(item, t, formatNumber)
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
