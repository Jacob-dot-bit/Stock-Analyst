import { Fragment, useState } from 'react'
import type { Score, ScreenerCandidate } from '../api/types'
import { useI18n } from '../i18n'
import { useHiddenColumns } from '../hooks/useHiddenColumns'
import { ColumnPicker } from './ColumnPicker'
import { InsightsBadge } from './InsightsBadge'
import { InsightsDetailRow } from './InsightsDetailRow'
import { PriceStatusBadge } from './PriceStatusBadge'
import { ScoreBadge } from './ScoreBadge'
import { ScoreDetailRow } from './ScoreDetailRow'
import { SortableHeader, type SortState } from './SortableHeader'
import { Sparkline } from './Sparkline'

interface Props {
  items: ScreenerCandidate[]
  sparklines: Record<number, number[]>
  scores: Record<number, Score>
  onDelete: (id: number) => void
  onUpdate: (id: number, payload: { company_name: string | null }) => Promise<{ duplicate_warning: string | null }>
  /** Shared with `DiscoveryPanel` via the parent page (`Screener.tsx`) —
   * one price filter for every "hidden gems" list on the page, not a
   * separate control per list. Empty string means "no bound". */
  priceMin: string
  priceMax: string
}

type SortableKey = 'symbol' | 'type' | 'price' | 'score' | 'added'

function sortValue(item: ScreenerCandidate, key: SortableKey, scores: Record<number, Score>): string | number | null {
  switch (key) {
    case 'symbol':
      return item.instrument.broker_symbol
    case 'type':
      return item.instrument.category ?? ''
    case 'price':
      return item.current_price
    case 'score':
      return scores[item.instrument.id]?.composite ?? null
    case 'added':
      return item.added_at
  }
}

export function ScreenerTable({ items, sparklines, scores, onDelete, onUpdate, priceMin, priceMax }: Props) {
  const { t, formatNumber, formatDate } = useI18n()
  // The server already ranks by composite score descending — default the
  // table's own sort to match, since ranking is the whole point of a
  // screener (unlike the watchlist, which defaults to most-recently-added).
  const [sort, setSort] = useState<SortState<SortableKey>>({ key: 'score', direction: 'desc' })
  const [search, setSearch] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [expandedInsightsId, setExpandedInsightsId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [companyNameDraft, setCompanyNameDraft] = useState('')
  const [rowBusy, setRowBusy] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)
  const [rowWarning, setRowWarning] = useState<string | null>(null)
  const { hidden, toggle } = useHiddenColumns('stock-analyst.screener.columns')

  function handleSort(key: SortableKey) {
    setSort((prev) => (prev.key === key ? { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' } : { key, direction: 'asc' }))
  }

  function startEdit(item: ScreenerCandidate) {
    setEditingId(item.id)
    setCompanyNameDraft(item.instrument.name ?? '')
    setRowError(null)
    setRowWarning(null)
  }

  function cancelEdit() {
    setEditingId(null)
    setRowError(null)
  }

  async function saveEdit(id: number) {
    setRowBusy(true)
    setRowError(null)
    setRowWarning(null)
    try {
      const result = await onUpdate(id, { company_name: companyNameDraft.trim() || null })
      setEditingId(null)
      if (result.duplicate_warning) setRowWarning(result.duplicate_warning)
    } catch (err) {
      setRowError(err instanceof Error ? err.message : String(err))
    } finally {
      setRowBusy(false)
    }
  }

  const columns = [
    { key: 'type', label: t('table.type') },
    { key: 'price', label: t('table.price') },
    { key: 'trend', label: t('table.trend') },
    { key: 'score', label: t('table.score') },
    { key: 'added', label: t('watchlist.addedOn') },
    { key: 'insights', label: t('table.insights') },
  ]

  if (items.length === 0) {
    return <div className="empty">{t('gems.empty')}</div>
  }

  const query = search.trim().toLowerCase()
  // Empty string parses to NaN, not 0 — comparisons against NaN are always
  // false, so an empty bound must map to `null` (no bound) explicitly
  // rather than relying on that fallthrough.
  const minPrice = priceMin.trim() === '' ? null : Number(priceMin)
  const maxPrice = priceMax.trim() === '' ? null : Number(priceMax)
  const visible = items
    .filter(
      (i) =>
        !query ||
        i.instrument.broker_symbol.toLowerCase().includes(query) ||
        (i.instrument.name?.toLowerCase().includes(query) ?? false),
    )
    .filter((i) => {
      if (minPrice === null && maxPrice === null) return true
      // A candidate with no known price can't be confirmed to be within a
      // price filter's range — excluded rather than shown as a false match.
      if (i.current_price === null) return false
      if (minPrice !== null && i.current_price < minPrice) return false
      if (maxPrice !== null && i.current_price > maxPrice) return false
      return true
    })
    .slice()
    .sort((a, b) => {
      const av = sortValue(a, sort.key, scores)
      const bv = sortValue(b, sort.key, scores)
      if (av === null || av === undefined) return bv === null || bv === undefined ? 0 : 1
      if (bv === null || bv === undefined) return -1

      const dir = sort.direction === 'asc' ? 1 : -1
      if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv) * dir
      return ((av as number) - (bv as number)) * dir
    })

  return (
    <>
      <div className="form-row" style={{ marginBottom: '0.8rem' }}>
        <div className="field">
          <label htmlFor="screener-search">{t('filters.search')}</label>
          <input id="screener-search" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <ColumnPicker columns={columns} hidden={hidden} onToggle={toggle} />
      </div>

      {rowError && (
        <div className="notice error" style={{ marginBottom: '0.8rem' }}>
          {rowError}
        </div>
      )}
      {rowWarning && (
        <div className="notice warning" style={{ marginBottom: '0.8rem' }}>
          {rowWarning}
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <SortableHeader label={t('table.instrument')} sortKeyName="symbol" sort={sort} onSort={handleSort} />
              {!hidden.has('type') && (
                <SortableHeader label={t('table.type')} sortKeyName="type" sort={sort} onSort={handleSort} />
              )}
              {!hidden.has('price') && (
                <SortableHeader label={t('table.price')} sortKeyName="price" sort={sort} onSort={handleSort} className="num" />
              )}
              {!hidden.has('trend') && <th>{t('table.trend')}</th>}
              {!hidden.has('score') && (
                <SortableHeader label={t('table.score')} sortKeyName="score" sort={sort} onSort={handleSort} className="num" />
              )}
              {!hidden.has('added') && (
                <SortableHeader label={t('watchlist.addedOn')} sortKeyName="added" sort={sort} onSort={handleSort} />
              )}
              {!hidden.has('insights') && <th>{t('table.insights')}</th>}
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map((item) => {
              const score = scores[item.instrument.id]

              return (
                <Fragment key={item.id}>
                  <tr>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <PriceStatusBadge instrument={item.instrument} />
                        <strong>{item.instrument.broker_symbol}</strong>
                      </div>
                      {editingId === item.id ? (
                        <input
                          style={{ fontSize: '0.78rem', marginTop: '0.2rem', width: '100%' }}
                          value={companyNameDraft}
                          placeholder={t('gems.form.companyNamePlaceholder')}
                          onChange={(e) => setCompanyNameDraft(e.target.value)}
                        />
                      ) : (
                        item.instrument.name && (
                          <div className="muted" style={{ fontSize: '0.78rem' }}>
                            {item.instrument.name}
                          </div>
                        )
                      )}
                    </td>
                    {!hidden.has('type') && (
                      <td>
                        {item.instrument.category ? (
                          <span className="tag neutral">{t(`breakdown.category.${item.instrument.category}`)}</span>
                        ) : (
                          '—'
                        )}
                      </td>
                    )}
                    {!hidden.has('price') && (
                      <td className="num">{item.current_price !== null ? formatNumber(item.current_price) : '—'}</td>
                    )}
                    {!hidden.has('trend') && (
                      <td>
                        <Sparkline closes={sparklines[item.instrument.id] ?? []} />
                      </td>
                    )}
                    {!hidden.has('score') && (
                      <td className="num">
                        <ScoreBadge
                          score={score}
                          expanded={expandedId === item.instrument.id}
                          onToggle={() => setExpandedId(expandedId === item.instrument.id ? null : item.instrument.id)}
                        />
                      </td>
                    )}
                    {!hidden.has('added') && <td>{formatDate(item.added_at)}</td>}
                    {!hidden.has('insights') && (
                      <td>
                        <InsightsBadge
                          expanded={expandedInsightsId === item.instrument.id}
                          onToggle={() =>
                            setExpandedInsightsId(expandedInsightsId === item.instrument.id ? null : item.instrument.id)
                          }
                        />
                      </td>
                    )}
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {editingId === item.id ? (
                        <>
                          <button className="link" disabled={rowBusy} onClick={() => void saveEdit(item.id)}>
                            {rowBusy ? t('common.saving') : t('common.save')}
                          </button>{' '}
                          <button className="link" disabled={rowBusy} onClick={cancelEdit}>
                            {t('common.cancel')}
                          </button>
                        </>
                      ) : (
                        <>
                          <button className="link" onClick={() => startEdit(item)}>
                            {t('common.edit')}
                          </button>{' '}
                          <button className="link" onClick={() => onDelete(item.id)}>
                            {t('common.delete')}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                  {expandedId === item.instrument.id && score && (
                    <ScoreDetailRow score={score} colSpan={2 + columns.filter((c) => !hidden.has(c.key)).length} />
                  )}
                  {expandedInsightsId === item.instrument.id && (
                    <InsightsDetailRow
                      instrumentId={item.instrument.id}
                      colSpan={2 + columns.filter((c) => !hidden.has(c.key)).length}
                    />
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}
