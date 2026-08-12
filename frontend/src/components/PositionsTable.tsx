import { useState } from 'react'
import type { Position } from '../api/types'
import { formatDate, formatMoney, formatNumber, formatQuantity, signClass } from '../format'
import { MappingCell } from './MappingCell'

interface Props {
  positions: Position[]
  baseCurrency: string
  onDelete: (id: number) => void
  onUpdated: () => void
}

type SortKey = 'symbol' | 'value' | 'pl' | 'plPct'

export function PositionsTable({ positions, baseCurrency, onDelete, onUpdated }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('value')
  const [account, setAccount] = useState<string>('all')

  if (positions.length === 0) {
    return (
      <div className="empty">
        Aucune position. Importez un relevé XTB ou ajoutez une ligne manuellement.
      </div>
    )
  }

  const accounts = [...new Set(positions.map((p) => p.account).filter(Boolean))] as string[]

  const visible = positions
    .filter((p) => account === 'all' || p.account === account)
    .slice()
    .sort((a, b) => {
      switch (sortKey) {
        case 'symbol':
          return a.instrument.broker_symbol.localeCompare(b.instrument.broker_symbol)
        case 'pl':
          return (b.broker_net_pl ?? -Infinity) - (a.broker_net_pl ?? -Infinity)
        case 'plPct':
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
            <label htmlFor="filter-account">Compte</label>
            <select id="filter-account" value={account} onChange={(e) => setAccount(e.target.value)}>
              <option value="all">Tous</option>
              {accounts.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="sort-key">Trier par</label>
          <select id="sort-key" value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
            <option value="value">Valeur de marché</option>
            <option value="pl">Résultat latent</option>
            <option value="plPct">Performance %</option>
            <option value="symbol">Symbole</option>
          </select>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Titre</th>
              <th>Correspondance</th>
              <th className="num">Qté</th>
              <th className="num">Prix de revient</th>
              <th className="num">Cours</th>
              <th className="num">Valeur ({baseCurrency})</th>
              <th className="num">Latent ({baseCurrency})</th>
              <th className="num">Perf.</th>
              <th>Depuis</th>
              <th>Compte</th>
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
                    {position.quantity < 0 && <span className="tag neutral">short</span>}
                  </div>
                  {position.instrument.name && (
                    <div className="muted" style={{ fontSize: '0.78rem' }}>
                      {position.instrument.name}
                      {position.lots_count > 1 && ` · ${position.lots_count} lots`}
                    </div>
                  )}
                </td>
                <td>
                  <MappingCell instrument={position.instrument} onUpdated={onUpdated} />
                </td>
                <td className="num">{formatQuantity(position.quantity)}</td>
                <td className="num">{formatMoney(position.avg_price, position.currency)}</td>
                <td className="num">{formatNumber(position.market_price)}</td>
                <td className="num">{formatNumber(position.broker_market_value)}</td>
                <td className={`num ${signClass(position.broker_net_pl)}`}>
                  {formatNumber(position.broker_net_pl)}
                </td>
                <td className={`num ${signClass(position.broker_net_pl_pct)}`}>
                  {position.broker_net_pl_pct === null
                    ? '—'
                    : `${position.broker_net_pl_pct > 0 ? '+' : ''}${formatNumber(
                        position.broker_net_pl_pct,
                      )} %`}
                </td>
                <td>{formatDate(position.opened_at)}</td>
                <td>
                  <span className={`tag ${position.source === 'MANUAL' ? 'manual' : 'neutral'}`}>
                    {position.account ?? (position.source === 'MANUAL' ? 'manuelle' : '—')}
                  </span>
                </td>
                <td>
                  <button className="link" onClick={() => onDelete(position.id)}>
                    Supprimer
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
