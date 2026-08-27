import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { SymbolSearchResult } from '../api/types'
import { useI18n } from '../i18n'

interface Props {
  onCreated: () => void
}

//: Same debounce as `ManualPositionForm` — avoids firing a request (and
//: spending FMP's quota) on every character typed.
const SEARCH_DEBOUNCE_MS = 350

export function AddToWatchlistForm({ onCreated }: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [targetPrice, setTargetPrice] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
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
    setCompanyName(result.name)
    setShowSuggestions(false)
    setSuggestions([])
  }

  // Accept both decimal separators, same reasoning as ManualPositionForm.
  const targetPriceValue = targetPrice.trim() === '' ? null : Number(targetPrice.replace(',', '.'))
  const valid = symbol.trim().length > 0 && (targetPriceValue === null || (Number.isFinite(targetPriceValue) && targetPriceValue > 0))

  async function submit() {
    setBusy(true)
    setError(null)
    setWarning(null)
    try {
      const created = await api.addWatchlistItem({
        broker_symbol: symbol.trim().toUpperCase(),
        target_entry_price: targetPriceValue,
        note: note.trim() || null,
        company_name: companyName.trim() || null,
      })
      setSymbol('')
      setCompanyName('')
      setTargetPrice('')
      setNote('')
      onCreated()
      // A duplicate warning is a soft signal, not an error — the item was
      // still added. Keep the form open so the user actually reads it,
      // instead of closing immediately and losing it.
      if (created.duplicate_warning) {
        setWarning(created.duplicate_warning)
      } else {
        setOpen(false)
      }
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
            <h2 style={{ marginBottom: '0.2rem' }}>{t('watchlist.form.title')}</h2>
            <span className="muted">{t('watchlist.form.subtitle')}</span>
          </div>
          <button onClick={() => setOpen(true)}>{t('common.add')}</button>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <h2>{t('watchlist.form.newTitle')}</h2>

      <div className="form-row">
        <div className="field" style={{ position: 'relative' }}>
          <label htmlFor="wl-symbol">{t('watchlist.form.symbol')}</label>
          <input
            id="wl-symbol"
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
          <label htmlFor="wl-company">{t('watchlist.form.companyName')}</label>
          <input
            id="wl-company"
            value={companyName}
            placeholder={t('watchlist.form.companyNamePlaceholder')}
            onChange={(e) => setCompanyName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="wl-target">{t('watchlist.form.targetPrice')}</label>
          <input
            id="wl-target"
            value={targetPrice}
            placeholder="150.00"
            onChange={(e) => setTargetPrice(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="wl-note">{t('watchlist.form.note')}</label>
          <input id="wl-note" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <button className="primary" disabled={!valid || busy} onClick={() => void submit()}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
        <button onClick={() => setOpen(false)}>{t('common.cancel')}</button>
      </div>

      {error && (
        <div className="notice error" style={{ marginTop: '0.8rem', marginBottom: 0 }}>
          {error}
        </div>
      )}
      {warning && (
        <div className="notice warning" style={{ marginTop: '0.8rem', marginBottom: 0 }}>
          {warning}
        </div>
      )}
    </div>
  )
}
