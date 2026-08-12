import { useState } from 'react'
import type { Position } from '../api/types'
import { signClass } from '../format'
import { useI18n } from '../i18n'
import { MappingCell } from './MappingCell'

interface Props {
  positions: Position[]
  baseCurrency: string
  onDelete: (id: number) => void
  onUpdated: () => void
}

type SortKey = 'symbol' | 'value' | 'unrealized' | 'performance'

export function PositionsTable({ positions, baseCurrency, onDelete, onUpdated }: Props) {
  const { t, formatNumber, formatSignedPercent, formatDate } = useI18n()
  const [sortKey, setSortKey] = useState<SortKey>('value')
  const [account, setAccount] = useState<string>('all')

  if (positions.length === 0) {
    return <div className="empty">{t('table.empty')}</div>
  }

  const accounts = [...new Set(positions.map((p) => p.account).filter(Boolean))] as string[]

  const visible = positions
    .filter((p) => account === 'all' || p.account === account)
    .slice()
    .sort((a, b) => {
      switch (sortKey) {
        case 'symbol':
          return a.instrument.broker_symbol.localeCompare(b.instrument.broker_symbol)
        case 'unrealized':
          return (b.broker_net_pl ?? -Infinity) - (a.broker_net_pl ?? -Infinity)
        case 'performance':
          return (b.broker_net_pl_pct ?? -Infinity) - (a.broker_net_pl_pct ?? -Infinity)
        default:
          return (b.broker_market_value ?? -Infinity) - (a.broker_market_value ?? -Infinity)
      }
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
          <label htmlFor="sort-key">{t('filters.sortBy')}</label>
          <select id="sort-key" value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
            <option value="value">{t('sort.value')}</option>
            <option value="unrealized">{t('sort.unrealized')}</option>
            <option value="performance">{t('sort.performance')}</option>
            <option value="symbol">{t('sort.symbol')}</option>
          </select>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('table.instrument')}</th>
              <th>{t('table.mapping')}</th>
              <th className="num">{t('table.quantity')}</th>
              <th className="num">{t('table.avgPrice')}</th>
              <th className="num">{t('table.price')}</th>
              <th className="num">{t('table.value', { currency: baseCurrency })}</th>
              <th className="num">{t('table.unrealized', { currency: baseCurrency })}</th>
              <th className="num">{t('table.performance')}</th>
              <th>{t('table.since')}</th>
              <th>{t('table.account')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map((position) => (
              <tr key={position.id}>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <strong>{position.instrument.broker_symbol}</strong>
                    {position.instrument.category && position.instrument.category !== 'STOCK' && (
                      <span className="tag neutral">{position.instrument.category}</span>
                    )}
                    {position.quantity < 0 && <span className="tag neutral">{t('table.short')}</span>}
                  </div>
                  {position.instrument.name && (
                    <div className="muted" style={{ fontSize: '0.78rem' }}>
                      {position.instrument.name}
                      {position.lots_count > 1 && ` · ${t('table.lots', { count: position.lots_count })}`}
                    </div>
                  )}
                </td>
                <td>
                  <MappingCell instrument={position.instrument} onUpdated={onUpdated} />
                </td>
                <td className="num">{formatNumber(position.quantity, 4)}</td>
                <td className="num">
                  {formatNumber(position.avg_price)}
                  {position.currency ? ` ${position.currency}` : ''}
                </td>
                <td className="num">{formatNumber(position.market_price)}</td>
                <td className="num">{formatNumber(position.broker_market_value)}</td>
                <td className={`num ${signClass(position.broker_net_pl)}`}>
                  {formatNumber(position.broker_net_pl)}
                </td>
                <td className={`num ${signClass(position.broker_net_pl_pct)}`}>
                  {formatSignedPercent(position.broker_net_pl_pct)}
                </td>
                <td>{formatDate(position.opened_at)}</td>
                <td>
                  <span className={`tag ${position.source === 'MANUAL' ? 'manual' : 'neutral'}`}>
                    {position.account ?? (position.source === 'MANUAL' ? t('table.manual') : '—')}
                  </span>
                </td>
                <td>
                  <button className="link" onClick={() => onDelete(position.id)}>
                    {t('common.delete')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
