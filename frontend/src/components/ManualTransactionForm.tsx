import { useState } from 'react'
import { api } from '../api/client'
import { useI18n } from '../i18n'

interface Props {
  onCreated: () => void
}

//: Mirrors `routers/transactions.py::MANUAL_TX_TYPES` — BUY/SELL/CLOSED_TRADE
//: are deliberately absent, see `transactions.manual.note`.
const MANUAL_TYPES = ['DIVIDEND', 'TAX', 'FEE', 'DEPOSIT', 'WITHDRAWAL', 'INTEREST', 'OTHER'] as const

export function ManualTransactionForm({ onCreated }: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [type, setType] = useState<string>('DIVIDEND')
  const [executedAt, setExecutedAt] = useState('')
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState('')
  const [account, setAccount] = useState('')
  const [symbol, setSymbol] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Accept both decimal separators — see ManualPositionForm for the same rule.
  const amountValue = Number(amount.replace(',', '.'))
  const valid = amount.trim() !== '' && Number.isFinite(amountValue)

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      await api.createTransaction({
        type,
        executed_at: executedAt || null,
        amount: amountValue,
        currency: currency.trim().toUpperCase() || null,
        account: account.trim() || null,
        broker_symbol: symbol.trim().toUpperCase() || null,
        comment: comment.trim() || null,
      })
      setType('DIVIDEND')
      setExecutedAt('')
      setAmount('')
      setCurrency('')
      setAccount('')
      setSymbol('')
      setComment('')
      setOpen(false)
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
          <div>
            <h2 className="compact">{t('transactions.manual.title')}</h2>
            <span className="muted">{t('transactions.manual.subtitle')}</span>
          </div>
          <button onClick={() => setOpen(true)}>{t('common.add')}</button>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <h2>{t('transactions.manual.newTitle')}</h2>

      <div className="form-row">
        <div className="field">
          <label htmlFor="tx-type">{t('transactions.type')}</label>
          <select id="tx-type" value={type} onChange={(e) => setType(e.target.value)}>
            {MANUAL_TYPES.map((tt) => (
              <option key={tt} value={tt}>
                {t(`transactions.type.${tt}`)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tx-date">{t('transactions.date')}</label>
          <input id="tx-date" type="date" value={executedAt} onChange={(e) => setExecutedAt(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="tx-amount">{t('transactions.amount')}</label>
          <input id="tx-amount" value={amount} placeholder="12.50" onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="tx-currency">{t('manual.currency')}</label>
          <input id="tx-currency" value={currency} placeholder="EUR" onChange={(e) => setCurrency(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="tx-account">{t('transactions.account')}</label>
          <input id="tx-account" value={account} onChange={(e) => setAccount(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="tx-symbol">{t('transactions.instrument')}</label>
          <input id="tx-symbol" value={symbol} placeholder="AAPL.US" onChange={(e) => setSymbol(e.target.value)} />
        </div>
        <button className="primary" disabled={!valid || busy} onClick={() => void submit()}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
        <button onClick={() => setOpen(false)}>{t('common.cancel')}</button>
      </div>

      <div className="field" style={{ marginTop: '0.6rem', maxWidth: '420px' }}>
        <label htmlFor="tx-comment">{t('transactions.comment')}</label>
        <input id="tx-comment" value={comment} onChange={(e) => setComment(e.target.value)} />
      </div>

      <p className="muted" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
        {t('transactions.manual.note')}
      </p>

      {error && (
        <div className="notice error" style={{ marginTop: '0.8rem', marginBottom: 0 }}>
          {error}
        </div>
      )}
    </div>
  )
}
