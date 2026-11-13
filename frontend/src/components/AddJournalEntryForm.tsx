import { useState } from 'react'
import { api } from '../api/client'
import { useI18n } from '../i18n'
import { SymbolInput } from './SymbolInput'

interface Props {
  onCreated: () => void
}

export function AddJournalEntryForm({ onCreated }: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const [thesis, setThesis] = useState('')
  const [reviewDate, setReviewDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const valid = thesis.trim().length > 0

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      await api.addJournalEntry({
        broker_symbol: symbol.trim() ? symbol.trim().toUpperCase() : null,
        thesis: thesis.trim(),
        review_date: reviewDate.trim() || null,
      })
      setSymbol('')
      setThesis('')
      setReviewDate('')
      onCreated()
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="compact">{t('journal.form.title')}</h2>
            <span className="muted">{t('journal.form.subtitle')}</span>
          </div>
          <button onClick={() => setOpen(true)}>{t('common.add')}</button>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <h2>{t('journal.form.title')}</h2>

      <div className="form-row">
        <SymbolInput
          id="journal-symbol"
          label={t('journal.form.symbol')}
          value={symbol}
          onChange={setSymbol}
        />
        <div className="field">
          <label htmlFor="journal-review-date">{t('journal.form.reviewDate')}</label>
          <input id="journal-review-date" type="date" value={reviewDate} onChange={(e) => setReviewDate(e.target.value)} />
        </div>
      </div>

      <div className="field" style={{ marginTop: '0.8rem' }}>
        <label htmlFor="journal-thesis">{t('journal.form.thesis')}</label>
        <textarea
          id="journal-thesis"
          rows={4}
          style={{ width: '100%' }}
          value={thesis}
          onChange={(e) => setThesis(e.target.value)}
        />
      </div>

      <div style={{ marginTop: '0.8rem' }}>
        <button className="primary" disabled={!valid || busy} onClick={() => void submit()}>
          {busy ? t('common.saving') : t('common.save')}
        </button>{' '}
        <button onClick={() => setOpen(false)}>{t('common.cancel')}</button>
      </div>

      {error && (
        <div className="notice error" style={{ marginTop: '0.8rem', marginBottom: 0 }}>
          {error}
        </div>
      )}
    </div>
  )
}
