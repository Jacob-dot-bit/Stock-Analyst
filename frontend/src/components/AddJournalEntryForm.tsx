import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { SymbolSearchResult } from '../api/types'
import { useI18n } from '../i18n'

interface Props {
  onCreated: () => void
}

//: Same debounce as AddToWatchlistForm — avoids firing a request (and
//: spending FMP's quota) on every character typed.
const SEARCH_DEBOUNCE_MS = 350

export function AddJournalEntryForm({ onCreated }: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const [thesis, setThesis] = useState('')
  const [reviewDate, setReviewDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [suggestions, setSuggestions] = useState<SymbolSearchResult[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const query = symbol.trim()
    if (query.length < 2 || query.includes('.')) {
      setSuggestions([])
      return
    }
    debounceRef.current = setTimeout(() => {
      api
        .searchSymbols(query)
        .then(setSuggestions)
        .catch(() => setSuggestions([]))
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [symbol])

  function pickSuggestion(result: SymbolSearchResult) {
    setSymbol(`${result.symbol}.US`)
    setShowSuggestions(false)
    setSuggestions([])
  }

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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
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
        <div className="field" style={{ position: 'relative' }}>
          <label htmlFor="journal-symbol">{t('journal.form.symbol')}</label>
          <input
            id="journal-symbol"
            value={symbol}
            placeholder="AAPL.US"
            autoComplete="off"
            onChange={(e) => setSymbol(e.target.value)}
            onFocus={() => setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
          />
          {showSuggestions && suggestions.length > 0 && (
            <ul className="symbol-suggestions">
              {suggestions.map((s) => (
                <li key={s.symbol}>
                  <button type="button" onClick={() => pickSuggestion(s)}>
                    <strong>{s.symbol}</strong> <span className="muted">{s.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
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
