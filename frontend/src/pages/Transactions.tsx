import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Transaction, TransactionList, TxType } from '../api/types'
import { ColumnPicker } from '../components/ColumnPicker'
import { ManualTransactionForm } from '../components/ManualTransactionForm'
import { signClass } from '../format'
import { useHiddenColumns } from '../hooks/useHiddenColumns'
import { useI18n } from '../i18n'

//: Grouped rather than one filter per raw TxType (9 values) — these are the
//: distinctions a user actually thinks in, not the ledger's own vocabulary.
const TYPE_GROUPS: { key: string; types: TxType[] }[] = [
  { key: 'all', types: [] },
  { key: 'dividends', types: ['DIVIDEND', 'TAX'] },
  { key: 'trades', types: ['BUY', 'SELL', 'CLOSED_TRADE'] },
  { key: 'fees', types: ['FEE'] },
  { key: 'cash', types: ['DEPOSIT', 'WITHDRAWAL', 'INTEREST'] },
]

/**
 * The transaction ledger — dividends, fees, trades, cash movements — with no
 * view anywhere else in the app before this page existed (item #10 of the
 * original UI list). The summary above the table always reflects whatever is
 * currently filtered, not a fixed lifetime total: "this year's dividends"
 * should summarise this year, not every year (see DEVLOG "Decision 3d.1").
 */
export function Transactions() {
  const { t, formatNumber, formatDate } = useI18n()
  const [group, setGroup] = useState('all')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [data, setData] = useState<TransactionList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState({ executed_at: '', amount: '', account: '', comment: '' })
  const [rowError, setRowError] = useState<string | null>(null)
  const [rowBusy, setRowBusy] = useState(false)
  const [search, setSearch] = useState('')
  const { hidden, toggle } = useHiddenColumns('stock-analyst.transactions.columns')

  const columns = [
    { key: 'type', label: t('transactions.type') },
    { key: 'instrument', label: t('transactions.instrument') },
    { key: 'account', label: t('transactions.account') },
    { key: 'amount', label: t('transactions.amount') },
    { key: 'instrumentEffect', label: t('transactions.instrumentEffect') },
    { key: 'currencyEffect', label: t('transactions.currencyEffect') },
    { key: 'comment', label: t('transactions.comment') },
  ]

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    const selected = TYPE_GROUPS.find((g) => g.key === group)
    return api
      .getTransactions({
        type: selected && selected.types.length > 0 ? selected.types : undefined,
        startDate: startDate || undefined,
        endDate: endDate || undefined,
      })
      .then((result) => {
        setData(result)
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        setLoading(false)
      })
  }, [group, startDate, endDate])

  useEffect(() => {
    void load()
  }, [load])

  function startEdit(tx: Transaction) {
    setEditingId(tx.id)
    setRowError(null)
    setEditDraft({
      executed_at: tx.executed_at ? tx.executed_at.slice(0, 10) : '',
      amount: tx.amount === null ? '' : String(tx.amount),
      account: tx.account ?? '',
      comment: tx.comment ?? '',
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setRowError(null)
  }

  async function saveEdit(id: number) {
    const amountValue = Number(editDraft.amount.replace(',', '.'))
    if (editDraft.amount.trim() === '' || !Number.isFinite(amountValue)) {
      setRowError(t('transactions.invalidAmount'))
      return
    }
    setRowBusy(true)
    setRowError(null)
    try {
      await api.updateTransaction(id, {
        executed_at: editDraft.executed_at ? new Date(editDraft.executed_at).toISOString() : undefined,
        amount: amountValue,
        account: editDraft.account,
        comment: editDraft.comment,
      })
      setEditingId(null)
      await load()
    } catch (err) {
      setRowError(err instanceof Error ? err.message : String(err))
    } finally {
      setRowBusy(false)
    }
  }

  async function remove(id: number) {
    setRowBusy(true)
    setRowError(null)
    try {
      await api.deleteTransaction(id)
      if (editingId === id) setEditingId(null)
      await load()
    } catch (err) {
      setRowError(err instanceof Error ? err.message : String(err))
    } finally {
      setRowBusy(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>{t('transactions.title')}</h1>
        <p>{t('transactions.subtitle')}</p>
        <Link to="/dividends" className="link">
          {t('transactions.viewDividends')}
        </Link>
      </div>

      {error && <div className="notice error">{error}</div>}

      {data && (
        <div className="stat-grid" style={{ marginBottom: 'var(--space-5)' }}>
          <div className="stat">
            <div className="label">{t('transactions.summary.netDividends')}</div>
            <div className={`value ${signClass(data.summary.net_dividends)}`}>
              {formatNumber(data.summary.net_dividends)}
            </div>
            <div className="muted" style={{ fontSize: '0.78rem', marginTop: '0.2rem' }}>
              {t('transactions.summary.grossAndTax', {
                gross: formatNumber(data.summary.total_dividends),
                tax: formatNumber(data.summary.total_withholding_tax),
              })}
            </div>
          </div>
          <div className="stat">
            <div className="label">{t('transactions.summary.fees')}</div>
            <div className={`value ${signClass(data.summary.total_fees)}`}>
              {formatNumber(data.summary.total_fees)}
            </div>
          </div>
          <div className="stat">
            <div className="label">{t('transactions.summary.realizedPl')}</div>
            <div className={`value ${signClass(data.summary.total_realized_pl)}`}>
              {formatNumber(data.summary.total_realized_pl)}
            </div>
            <div
              className="muted"
              style={{ fontSize: '0.78rem', marginTop: '0.2rem' }}
              title={t('transactions.currencyEffectTooltip')}
            >
              {t('transactions.summary.effectSplit', {
                instrument: formatNumber(data.summary.total_instrument_effect),
                currency: formatNumber(data.summary.total_currency_effect),
              })}
              {data.summary.closed_trades_with_effect < data.summary.closed_trades_total && (
                <>
                  {' '}
                  {t('transactions.summary.effectCoverage', {
                    resolved: data.summary.closed_trades_with_effect,
                    total: data.summary.closed_trades_total,
                  })}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      <ManualTransactionForm onCreated={() => void load()} />

      {rowError && (
        <div className="notice error" style={{ marginTop: '1.1rem', marginBottom: 0 }}>
          {rowError}
        </div>
      )}

      <div className="card" style={{ marginTop: '1.1rem' }}>
        <div className="form-row" style={{ marginBottom: '0.8rem' }}>
          <div className="field">
            <label htmlFor="tx-group">{t('filters.type')}</label>
            <select id="tx-group" value={group} onChange={(e) => setGroup(e.target.value)}>
              {TYPE_GROUPS.map((g) => (
                <option key={g.key} value={g.key}>
                  {t(`transactions.group.${g.key}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="tx-start">{t('filters.dateFrom')}</label>
            <input
              id="tx-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="tx-end">{t('filters.dateTo')}</label>
            <input id="tx-end" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="tx-search">{t('filters.search')}</label>
            <input id="tx-search" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <ColumnPicker columns={columns} hidden={hidden} onToggle={toggle} />
        </div>

        {(() => {
          const query = search.trim().toLowerCase()
          const filtered =
            data?.transactions.filter(
              (tx) =>
                !query ||
                (tx.comment?.toLowerCase().includes(query) ?? false) ||
                (tx.instrument?.broker_symbol.toLowerCase().includes(query) ?? false) ||
                (tx.account?.toLowerCase().includes(query) ?? false),
            ) ?? []

          if (loading) return <div className="empty">{t('common.loading')}</div>
          if (data && filtered.length === 0) return <div className="empty">{t('transactions.empty')}</div>
          if (!data) return null

          return (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t('transactions.date')}</th>
                    {!hidden.has('type') && <th>{t('transactions.type')}</th>}
                    {!hidden.has('instrument') && <th>{t('transactions.instrument')}</th>}
                    {!hidden.has('account') && <th>{t('transactions.account')}</th>}
                    {!hidden.has('amount') && <th className="num">{t('transactions.amount')}</th>}
                    {!hidden.has('instrumentEffect') && (
                      <th className="num" title={t('transactions.instrumentEffectTooltip')}>
                        {t('transactions.instrumentEffect')}
                      </th>
                    )}
                    {!hidden.has('currencyEffect') && (
                      <th className="num" title={t('transactions.currencyEffectTooltip')}>
                        {t('transactions.currencyEffect')}
                      </th>
                    )}
                    {!hidden.has('comment') && <th>{t('transactions.comment')}</th>}
                    <th>{t('transactions.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((tx) =>
                    editingId === tx.id ? (
                      <tr key={tx.id}>
                        <td>
                          <input
                            type="date"
                            value={editDraft.executed_at}
                            onChange={(e) => setEditDraft({ ...editDraft, executed_at: e.target.value })}
                          />
                        </td>
                        {!hidden.has('type') && (
                          <td>
                            <span className="tag neutral">{t(`transactions.type.${tx.type}`)}</span>
                          </td>
                        )}
                        {!hidden.has('instrument') && <td>{tx.instrument?.broker_symbol ?? '—'}</td>}
                        {!hidden.has('account') && (
                          <td>
                            <input
                              value={editDraft.account}
                              onChange={(e) => setEditDraft({ ...editDraft, account: e.target.value })}
                            />
                          </td>
                        )}
                        {!hidden.has('amount') && (
                          <td className="num">
                            <input
                              style={{ width: '6.5rem', textAlign: 'right' }}
                              value={editDraft.amount}
                              onChange={(e) => setEditDraft({ ...editDraft, amount: e.target.value })}
                            />
                            {tx.currency ? ` ${tx.currency}` : ''}
                          </td>
                        )}
                        {!hidden.has('instrumentEffect') && (
                          <td className={`num ${signClass(tx.instrument_effect)}`}>
                            {tx.instrument_effect === null ? '—' : formatNumber(tx.instrument_effect)}
                          </td>
                        )}
                        {!hidden.has('currencyEffect') && (
                          <td className={`num ${signClass(tx.currency_effect)}`}>
                            {tx.currency_effect === null ? '—' : formatNumber(tx.currency_effect)}
                          </td>
                        )}
                        {!hidden.has('comment') && (
                          <td>
                            <input
                              value={editDraft.comment}
                              onChange={(e) => setEditDraft({ ...editDraft, comment: e.target.value })}
                            />
                          </td>
                        )}
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <button
                            className="link"
                            disabled={rowBusy}
                            onClick={() => void saveEdit(tx.id)}
                          >
                            {rowBusy ? t('common.saving') : t('common.save')}
                          </button>{' '}
                          <button className="link" disabled={rowBusy} onClick={cancelEdit}>
                            {t('common.cancel')}
                          </button>
                        </td>
                      </tr>
                    ) : (
                      <tr key={tx.id}>
                        <td>{formatDate(tx.executed_at)}</td>
                        {!hidden.has('type') && (
                          <td>
                            <span className="tag neutral">{t(`transactions.type.${tx.type}`)}</span>
                          </td>
                        )}
                        {!hidden.has('instrument') && <td>{tx.instrument?.broker_symbol ?? '—'}</td>}
                        {!hidden.has('account') && <td>{tx.account ?? '—'}</td>}
                        {!hidden.has('amount') && (
                          <td className={`num ${tx.type === 'CLOSED_TRADE' ? signClass(tx.amount) : ''}`}>
                            {tx.amount === null ? '—' : formatNumber(tx.amount)}
                            {tx.currency ? ` ${tx.currency}` : ''}
                          </td>
                        )}
                        {!hidden.has('instrumentEffect') && (
                          <td className={`num ${signClass(tx.instrument_effect)}`}>
                            {tx.instrument_effect === null ? '—' : formatNumber(tx.instrument_effect)}
                          </td>
                        )}
                        {!hidden.has('currencyEffect') && (
                          <td className={`num ${signClass(tx.currency_effect)}`}>
                            {tx.currency_effect === null ? '—' : formatNumber(tx.currency_effect)}
                          </td>
                        )}
                        {!hidden.has('comment') && <td>{tx.comment ?? '—'}</td>}
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <button className="link" onClick={() => startEdit(tx)}>
                            {t('common.edit')}
                          </button>{' '}
                          <button className="link" disabled={rowBusy} onClick={() => void remove(tx.id)}>
                            {t('common.delete')}
                          </button>
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
          )
        })()}
      </div>
    </>
  )
}
