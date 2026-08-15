import { Fragment, useState } from 'react'
import type { Position, PositionSignal, Score } from '../api/types'
import { signClass } from '../format'
import { useI18n } from '../i18n'
import { useHiddenColumns } from '../hooks/useHiddenColumns'
import { ColumnPicker } from './ColumnPicker'
import { InsightsBadge } from './InsightsBadge'
import { MappingCell } from './MappingCell'
import { PositionDetailRow } from './PositionDetailRow'
import { PriceStatusBadge } from './PriceStatusBadge'
import { ScoreBadge } from './ScoreBadge'
import { SignalBadge } from './SignalBadge'
import { SortableHeader } from './SortableHeader'
import { Sparkline } from './Sparkline'

interface Props {
  positions: Position[]
  baseCurrency: string
  /** Cached closes per instrument, keyed by id. Empty until prices are refreshed. */
  sparklines: Record<number, number[]>
  /** Composite + pillar scores per instrument, keyed by id. Empty for CFDs
   * and until a fundamentals refresh has run. */
  scores: Record<number, Score>
  /** Score + allocation-gap signal per instrument, keyed by id. See DEVLOG
   * "Decision 3u.19" — a fixed, transparent combination, never a trade
   * instruction. */
  signals: Record<number, PositionSignal>
  onDelete: (id: number) => void
  onUpdated: () => void
}

type SortableKey =
  | 'symbol'
  | 'type'
  | 'quantity'
  | 'avgPrice'
  | 'price'
  | 'value'
  | 'weight'
  | 'unrealized'
  | 'performance'
  | 'score'
  | 'since'
  | 'account'

interface SortState {
  key: SortableKey
  direction: 'asc' | 'desc'
}

function sortValue(
  position: Position,
  key: SortableKey,
  scores: Record<number, Score>,
): string | number | null {
  switch (key) {
    case 'symbol':
      return position.instrument.broker_symbol
    case 'type':
      return position.instrument.category ?? ''
    case 'quantity':
      return position.quantity
    case 'avgPrice':
      return position.avg_price
    case 'price':
      return position.current_price ?? position.market_price
    case 'value':
      return position.current_value
    case 'weight':
      return position.weight_percent
    case 'unrealized':
      return position.current_unrealized_pl
    case 'performance':
      return position.current_unrealized_pl_pct
    case 'score':
      return scores[position.instrument.id]?.composite ?? null
    case 'since':
      return position.opened_at
    case 'account':
      return position.account ?? ''
  }
}

export function PositionsTable({ positions, baseCurrency, sparklines, scores, signals, onDelete, onUpdated }: Props) {
  const { t, formatNumber, formatSignedPercent, formatDate } = useI18n()
  const [sort, setSort] = useState<SortState>({ key: 'value', direction: 'desc' })
  const [account, setAccount] = useState<string>('all')
  const [search, setSearch] = useState('')
  // One consolidated "Détails" panel per position, replacing the separate
  // Score/Insights expand rows this table used to have — see DEVLOG
  // "Decision 3u.31". Watchlist/Screener keep the separate-toggle
  // behavior; `ScoreBadge`/`InsightsBadge` are shared components whose
  // visuals are reused here unchanged, only retargeted to open this one
  // panel instead of their own independent row.
  const [expandedDetailId, setExpandedDetailId] = useState<number | null>(null)
  const { hidden, toggle } = useHiddenColumns('stock-analyst.positions.columns')

  function handleSort(key: SortableKey) {
    setSort((prev) => (prev.key === key ? { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' } : { key, direction: 'asc' }))
  }

  const columns = [
    { key: 'type', label: t('table.type') },
    { key: 'mapping', label: t('table.mapping') },
    { key: 'quantity', label: t('table.quantity') },
    { key: 'avgPrice', label: t('table.avgPrice') },
    { key: 'price', label: t('table.price') },
    { key: 'trend', label: t('table.trend') },
    { key: 'value', label: t('table.value', { currency: baseCurrency }) },
    { key: 'weight', label: t('table.weight') },
    { key: 'unrealized', label: t('table.unrealized', { currency: baseCurrency }) },
    { key: 'performance', label: t('table.performance') },
    { key: 'score', label: t('table.score') },
    { key: 'signal', label: t('table.signal') },
    { key: 'since', label: t('table.since') },
    { key: 'account', label: t('table.account') },
    { key: 'insights', label: t('table.insights') },
  ]

  if (positions.length === 0) {
    return <div className="empty">{t('table.empty')}</div>
  }

  const accounts = [...new Set(positions.map((p) => p.account).filter(Boolean))] as string[]
  const query = search.trim().toLowerCase()

  const visible = positions
    .filter((p) => account === 'all' || p.account === account)
    .filter(
      (p) =>
        !query ||
        p.instrument.broker_symbol.toLowerCase().includes(query) ||
        (p.instrument.name?.toLowerCase().includes(query) ?? false),
    )
    .slice()
    .sort((a, b) => {
      const av = sortValue(a, sort.key, scores)
      const bv = sortValue(b, sort.key, scores)
      // Missing values always sort last, regardless of direction — the same
      // "never guess" convention this app applies everywhere else: a blank
      // isn't the lowest or highest value, it's unknown.
      if (av === null || av === undefined) return bv === null || bv === undefined ? 0 : 1
      if (bv === null || bv === undefined) return -1

      const dir = sort.direction === 'asc' ? 1 : -1
      if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv) * dir
      return ((av as number) - (bv as number)) * dir
    })

  return (
    <>
      <div className="form-row" style={{ marginBottom: '0.8rem' }}>
        {accounts.length > 1 && (
          <div className="field">
            <label htmlFor="filter-account">{t('filters.account')}</label>
            <select id="filter-account" value={account} onChange={(e) => setAccount(e.target.value)}>
              <option value="all">{t('filters.all')}</option>
              {accounts.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="filter-search">{t('filters.search')}</label>
          <input id="filter-search" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <ColumnPicker columns={columns} hidden={hidden} onToggle={toggle} />
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <SortableHeader label={t('table.instrument')} sortKeyName="symbol" sort={sort} onSort={handleSort} />
              {!hidden.has('type') && (
                <SortableHeader label={t('table.type')} sortKeyName="type" sort={sort} onSort={handleSort} />
              )}
              {!hidden.has('mapping') && <th>{t('table.mapping')}</th>}
              {!hidden.has('quantity') && (
                <SortableHeader
                  label={t('table.quantity')}
                  sortKeyName="quantity"
                  sort={sort}
                  onSort={handleSort}
                  className="num"
                />
              )}
              {!hidden.has('avgPrice') && (
                <SortableHeader
                  label={t('table.avgPrice')}
                  sortKeyName="avgPrice"
                  sort={sort}
                  onSort={handleSort}
                  className="num"
                  title={t('table.avgPriceTooltip')}
                />
              )}
              {!hidden.has('price') && (
                <SortableHeader label={t('table.price')} sortKeyName="price" sort={sort} onSort={handleSort} className="num" />
              )}
              {!hidden.has('trend') && <th>{t('table.trend')}</th>}
              {!hidden.has('value') && (
                <SortableHeader
                  label={t('table.value', { currency: baseCurrency })}
                  sortKeyName="value"
                  sort={sort}
                  onSort={handleSort}
                  className="num"
                />
              )}
              {!hidden.has('weight') && (
                <SortableHeader
                  label={t('table.weight')}
                  sortKeyName="weight"
                  sort={sort}
                  onSort={handleSort}
                  className="num"
                  title={t('table.weightTooltip')}
                />
              )}
              {!hidden.has('unrealized') && (
                <SortableHeader
                  label={t('table.unrealized', { currency: baseCurrency })}
                  sortKeyName="unrealized"
                  sort={sort}
                  onSort={handleSort}
                  className="num"
                />
              )}
              {!hidden.has('performance') && (
                <SortableHeader
                  label={t('table.performance')}
                  sortKeyName="performance"
                  sort={sort}
                  onSort={handleSort}
                  className="num"
                />
              )}
              {!hidden.has('score') && (
                <SortableHeader
                  label={t('table.score')}
                  sortKeyName="score"
                  sort={sort}
                  onSort={handleSort}
                  className="num"
                  title={t('table.scoreTooltip')}
                />
              )}
              {!hidden.has('signal') && <th>{t('table.signal')}</th>}
              {!hidden.has('since') && (
                <SortableHeader label={t('table.since')} sortKeyName="since" sort={sort} onSort={handleSort} />
              )}
              {!hidden.has('account') && (
                <SortableHeader label={t('table.account')} sortKeyName="account" sort={sort} onSort={handleSort} />
              )}
              {!hidden.has('insights') && <th>{t('table.insights')}</th>}
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map((position) => (
              <Fragment key={position.id}>
              <tr>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <PriceStatusBadge instrument={position.instrument} valuationNote={position.valuation_note} />
                    <strong>{position.instrument.broker_symbol}</strong>
                    {position.quantity < 0 && <span className="tag neutral">{t('table.short')}</span>}
                  </div>
                  {position.instrument.name && (
                    <div className="muted" style={{ fontSize: '0.78rem' }}>
                      {position.instrument.name}
                      {position.lots_count > 1 && ` · ${t('table.lots', { count: position.lots_count })}`}
                    </div>
                  )}
                </td>
                {!hidden.has('type') && (
                  <td>
                    {position.instrument.category ? (
                      <span className="tag neutral">
                        {t(`breakdown.category.${position.instrument.category}`)}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                )}
                {!hidden.has('mapping') && (
                  <td>
                    <MappingCell instrument={position.instrument} onUpdated={onUpdated} />
                  </td>
                )}
                {!hidden.has('quantity') && <td className="num">{formatNumber(position.quantity, 4)}</td>}
                {!hidden.has('avgPrice') && (
                  <td
                    className="num"
                    title={
                      position.instrument.category === 'P2P'
                        ? t('table.avgPriceNotApplicableTooltip', {
                            date: position.opened_at ? formatDate(position.opened_at) : '—',
                          })
                        : undefined
                    }
                  >
                    {position.instrument.category === 'P2P' ? (
                      t('common.notApplicable')
                    ) : (
                      <>
                        {formatNumber(position.avg_price)}
                        {position.currency ? ` ${position.currency}` : ''}
                      </>
                    )}
                  </td>
                )}
                {!hidden.has('price') && (
                  <td className="num">{formatNumber(position.current_price ?? position.market_price)}</td>
                )}
                {!hidden.has('trend') && (
                  <td>
                    <Sparkline closes={sparklines[position.instrument.id] ?? []} />
                  </td>
                )}
                {!hidden.has('value') && (
                  <td
                    className="num"
                    title={
                      position.valuation_note
                        ? t(position.valuation_note.code, position.valuation_note.params)
                        : position.current_value === null
                          ? t('table.valueNotComputableTooltip')
                          : undefined
                    }
                  >
                    {formatNumber(position.current_value)}
                  </td>
                )}
                {!hidden.has('weight') && (
                  <td className="num">
                    {position.weight_percent !== null ? (
                      <span className={position.weight_percent > 15 ? 'weight-high' : ''}>
                        {formatNumber(position.weight_percent, 1)}%
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                )}
                {!hidden.has('unrealized') && (
                  <td className={`num ${signClass(position.current_unrealized_pl)}`}>
                    {formatNumber(position.current_unrealized_pl)}
                  </td>
                )}
                {!hidden.has('performance') && (
                  <td className={`num ${signClass(position.current_unrealized_pl_pct)}`}>
                    {formatSignedPercent(position.current_unrealized_pl_pct)}
                  </td>
                )}
                {!hidden.has('score') && (
                  <td className="num">
                    <ScoreBadge
                      score={scores[position.instrument.id]}
                      expanded={expandedDetailId === position.instrument.id}
                      onToggle={() =>
                        setExpandedDetailId(
                          expandedDetailId === position.instrument.id ? null : position.instrument.id,
                        )
                      }
                    />
                  </td>
                )}
                {!hidden.has('signal') && (
                  <td>
                    {(() => {
                      const signal = signals[position.instrument.id]
                      if (!signal) return '—'

                      const label =
                        signal.signal === 'reinforce'
                          ? t('signals.positionReinforceFact')
                          : signal.signal === 'reduce'
                            ? t('signals.positionReduceFact')
                            : signal.signal === 'hold'
                              ? t('signals.hold')
                              : t('signals.not_applicable')

                      // Only "under"/"over" have a real gap to show — "within"
                      // and "no_target" always carry gap_pct === 0, and
                      // appending "(0.0 pts)" to those would read as a real
                      // measurement instead of the absence of one.
                      const stateLabel = t(`allocation.state.${signal.allocation_state}`)
                      const gapSuffix =
                        signal.allocation_state === 'under' || signal.allocation_state === 'over'
                          ? ` (${formatNumber(signal.gap_pct, 1)} pts)`
                          : ''

                      return (
                        <SignalBadge
                          signal={signal.signal}
                          label={label}
                          title={t('signals.positionTooltip', {
                            score: signal.composite_score !== null ? formatNumber(signal.composite_score, 0) : '—',
                            band: t(`signals.band.${signal.score_band}`),
                            category: signal.category
                              ? t(`breakdown.category.${signal.category}`)
                              : t('breakdown.unknown'),
                            state: stateLabel + gapSuffix,
                          })}
                        />
                      )
                    })()}
                  </td>
                )}
                {!hidden.has('since') && <td>{formatDate(position.opened_at)}</td>}
                {!hidden.has('account') && (
                  <td>
                    <span className={`tag ${position.source === 'MANUAL' ? 'manual' : 'neutral'}`}>
                      {position.account ?? (position.source === 'MANUAL' ? t('table.manual') : '—')}
                    </span>
                  </td>
                )}
                {!hidden.has('insights') && (
                  <td>
                    <InsightsBadge
                      expanded={expandedDetailId === position.instrument.id}
                      onToggle={() =>
                        setExpandedDetailId(
                          expandedDetailId === position.instrument.id ? null : position.instrument.id,
                        )
                      }
                    />
                  </td>
                )}
                <td>
                  <button
                    className="link"
                    onClick={() => {
                      if (window.confirm(t('table.deleteConfirm', { symbol: position.instrument.broker_symbol }))) {
                        onDelete(position.id)
                      }
                    }}
                  >
                    {t('common.delete')}
                  </button>
                </td>
              </tr>
              {expandedDetailId === position.instrument.id && (
                <PositionDetailRow
                  position={position}
                  score={scores[position.instrument.id]}
                  signal={signals[position.instrument.id]}
                  baseCurrency={baseCurrency}
                  colSpan={2 + columns.filter((c) => !hidden.has(c.key)).length}
                />
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
