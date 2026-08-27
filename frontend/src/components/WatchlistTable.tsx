import { Fragment, useState } from 'react'
import type { Score, WatchlistItem, WatchlistSignal } from '../api/types'
import { signClass } from '../format'
import { useI18n } from '../i18n'
import { useHiddenColumns } from '../hooks/useHiddenColumns'
import { ColumnPicker } from './ColumnPicker'
import { InsightsBadge } from './InsightsBadge'
import { InsightsDetailRow } from './InsightsDetailRow'
import { PriceStatusBadge } from './PriceStatusBadge'
import { ScoreBadge } from './ScoreBadge'
import { ScoreDetailRow } from './ScoreDetailRow'
import { SignalBadge } from './SignalBadge'
import { SortableHeader, type SortState } from './SortableHeader'
import { Sparkline } from './Sparkline'

interface Props {
  items: WatchlistItem[]
  sparklines: Record<number, number[]>
  scores: Record<number, Score>
  /** Score + target-price signal per instrument, keyed by id. See DEVLOG
   * "Decision 3u.19" — a fixed, transparent combination, never a trade
   * instruction. */
  signals: Record<number, WatchlistSignal>
  onDelete: (id: number) => void
  onUpdate: (
    id: number,
    payload: { target_entry_price: number | null; note: string | null; company_name: string | null },
  ) => Promise<{ duplicate_warning: string | null }>
}

type SortableKey = 'symbol' | 'type' | 'price' | 'target' | 'distance' | 'score' | 'added'

function sortValue(item: WatchlistItem, key: SortableKey, scores: Record<number, Score>): string | number | null {
  switch (key) {
    case 'symbol':
      return item.instrument.broker_symbol
    case 'type':
      return item.instrument.category ?? ''
    case 'price':
      return item.current_price
    case 'target':
      return item.target_entry_price
    case 'distance':
      return item.distance_to_target_pct
    case 'score':
      return scores[item.instrument.id]?.composite ?? null
    case 'added':
      return item.added_at
  }
}

export function WatchlistTable({ items, sparklines, scores, signals, onDelete, onUpdate }: Props) {
  const { t, formatNumber, formatSignedPercent, formatDate } = useI18n()
  const [sort, setSort] = useState<SortState<SortableKey>>({ key: 'added', direction: 'desc' })
  const [search, setSearch] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [expandedInsightsId, setExpandedInsightsId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState({ target: '', note: '', companyName: '' })
  const [rowBusy, setRowBusy] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)
  const [rowWarning, setRowWarning] = useState<string | null>(null)
  const { hidden, toggle } = useHiddenColumns('stock-analyst.watchlist.columns')

  function handleSort(key: SortableKey) {
    setSort((prev) => (prev.key === key ? { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' } : { key, direction: 'asc' }))
  }

  function startEdit(item: WatchlistItem) {
    setEditingId(item.id)
    setEditDraft({
      target: item.target_entry_price !== null ? String(item.target_entry_price) : '',
      note: item.note ?? '',
      companyName: item.instrument.name ?? '',
    })
    setRowError(null)
    setRowWarning(null)
  }

  function cancelEdit() {
    setEditingId(null)
    setRowError(null)
  }

  async function saveEdit(id: number) {
    // Accept both decimal separators, same reasoning as ManualPositionForm.
    const trimmed = editDraft.target.trim()
    const targetValue = trimmed === '' ? null : Number(trimmed.replace(',', '.'))
    if (targetValue !== null && (!Number.isFinite(targetValue) || targetValue <= 0)) {
      setRowError(t('watchlist.invalidTarget'))
      return
    }
    setRowBusy(true)
    setRowError(null)
    setRowWarning(null)
    try {
      const result = await onUpdate(id, {
        target_entry_price: targetValue,
        note: editDraft.note.trim() || null,
        company_name: editDraft.companyName.trim() || null,
      })
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
    { key: 'target', label: t('watchlist.targetPrice') },
    { key: 'distance', label: t('watchlist.distanceToTarget') },
    { key: 'score', label: t('table.score') },
    { key: 'signal', label: t('table.signal') },
    { key: 'note', label: t('watchlist.note') },
    { key: 'added', label: t('watchlist.addedOn') },
    { key: 'insights', label: t('table.insights') },
  ]

  if (items.length === 0) {
    return <div className="empty">{t('watchlist.empty')}</div>
  }

  const query = search.trim().toLowerCase()
  const visible = items
    .filter(
      (i) =>
        !query ||
        i.instrument.broker_symbol.toLowerCase().includes(query) ||
        (i.instrument.name?.toLowerCase().includes(query) ?? false),
    )
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
          <label htmlFor="watchlist-search">{t('filters.search')}</label>
          <input id="watchlist-search" value={search} onChange={(e) => setSearch(e.target.value)} />
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
              {!hidden.has('target') && (
                <SortableHeader
                  label={t('watchlist.targetPrice')}
                  sortKeyName="target"
                  sort={sort}
                  onSort={handleSort}
                  className="num"
                />
              )}
              {!hidden.has('distance') && (
                <SortableHeader
                  label={t('watchlist.distanceToTarget')}
                  sortKeyName="distance"
                  sort={sort}
                  onSort={handleSort}
                  className="num"
                />
              )}
              {!hidden.has('score') && (
                <SortableHeader label={t('table.score')} sortKeyName="score" sort={sort} onSort={handleSort} className="num" />
              )}
              {!hidden.has('signal') && <th>{t('table.signal')}</th>}
              {!hidden.has('note') && <th>{t('watchlist.note')}</th>}
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
              const signal = signals[item.instrument.id]
              const isOpportunity = signal?.signal === 'reinforce'

              return (
                <Fragment key={item.id}>
                  <tr className={isOpportunity ? 'watchlist-opportunity' : ''}>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <PriceStatusBadge instrument={item.instrument} />
                        <strong>{item.instrument.broker_symbol}</strong>
                      </div>
                      {editingId === item.id ? (
                        <input
                          style={{ fontSize: '0.78rem', marginTop: '0.2rem', width: '100%' }}
                          value={editDraft.companyName}
                          placeholder={t('watchlist.form.companyNamePlaceholder')}
                          onChange={(e) => setEditDraft({ ...editDraft, companyName: e.target.value })}
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
                    {!hidden.has('target') && (
                      <td className="num">
                        {editingId === item.id ? (
                          <input
                            style={{ width: '6rem', textAlign: 'right' }}
                            value={editDraft.target}
                            placeholder={t('watchlist.form.targetPrice')}
                            onChange={(e) => setEditDraft({ ...editDraft, target: e.target.value })}
                          />
                        ) : item.target_entry_price !== null ? (
                          formatNumber(item.target_entry_price)
                        ) : (
                          '—'
                        )}
                      </td>
                    )}
                    {!hidden.has('distance') && (
                      <td className={`num ${signClass(item.distance_to_target_pct === null ? null : -item.distance_to_target_pct)}`}>
                        {item.distance_to_target_pct !== null ? formatSignedPercent(item.distance_to_target_pct) : '—'}
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
                    {!hidden.has('signal') && (
                      <td>
                        {signal ? (
                          <SignalBadge
                            signal={signal.signal}
                            label={
                              signal.signal === 'reinforce'
                                ? t('signals.watchlistReinforceFact')
                                : signal.signal === 'hold'
                                  ? t('signals.hold')
                                  : t('signals.not_applicable')
                            }
                            title={t('signals.watchlistTooltip', {
                              score: signal.composite_score !== null ? formatNumber(signal.composite_score, 0) : '—',
                              band: t(`signals.band.${signal.score_band}`),
                              distance:
                                signal.distance_to_target_pct !== null
                                  ? formatSignedPercent(signal.distance_to_target_pct)
                                  : '—',
                            })}
                          />
                        ) : (
                          '—'
                        )}
                      </td>
                    )}
                    {!hidden.has('note') && (
                      <td className="muted">
                        {editingId === item.id ? (
                          <input
                            value={editDraft.note}
                            onChange={(e) => setEditDraft({ ...editDraft, note: e.target.value })}
                          />
                        ) : (
                          item.note ?? '—'
                        )}
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
