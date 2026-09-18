import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { SymbolSearchResult } from '../api/types'
import { useI18n } from '../i18n'

interface Props {
  onCreated: () => void
}

//: How long to wait after the last keystroke before searching — avoids
//: firing a request (and spending FMP's quota) on every character typed.
const SEARCH_DEBOUNCE_MS = 350

export function ManualPositionForm({ onCreated }: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [currency, setCurrency] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [suggestions, setSuggestions] = useState<SymbolSearchResult[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Company-name search, debounced. Best-effort: if FMP has no key configured
  // (400) or the search otherwise fails, suggestions just stay empty rather
  // than surfacing an error — typing the symbol directly still works fine.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const query = symbol.trim()
    if (query.length < 2 || query.includes('.')) {
      // A broker-style symbol (has a dot, e.g. "AAPL.US") is not a company
      // name — skip searching once the user is clearly typing a ticker.
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
    // FMP's free tier only covers US listings, so the suggested symbol is
    // always a US ticker — append the broker-style ".US" suffix this app's
    // symbol resolution expects (see symbols/mapping.py).
    setSymbol(`${result.symbol}.US`)
    setShowSuggestions(false)
    setSuggestions([])
  }

  // Accept both decimal separators: a French or Polish keyboard produces a comma,
  // and rejecting "12,5" would look like a bug rather than a format rule.
  const quantityValue = Number(quantity.replace(',', '.'))
  const priceValue = Number(price.replace(',', '.'))
  const valid =
    symbol.trim().length > 0 &&
    quantity.trim() !== '' &&
    price.trim() !== '' &&
    Number.isFinite(quantityValue) &&
    Number.isFinite(priceValue) &&
    quantityValue !== 0

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      await api.createManualPosition({
        broker_symbol: symbol.trim().toUpperCase(),
        quantity: quantityValue,
        avg_price: priceValue,
        currency: currency.trim().toUpperCase() || null,
      })
      setSymbol('')
      setQuantity('')
      setPrice('')
      setCurrency('')
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
        <div
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}
        >
          <div>
            <h2 className="compact">{t('manual.title')}</h2>
            <span className="muted">{t('manual.subtitle')}</span>
          </div>
          <button onClick={() => setOpen(true)}>{t('common.add')}</button>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <h2>{t('manual.newTitle')}</h2>

      <div className="form-row">
        <div className="field" style={{ position: 'relative' }}>
          <label htmlFor="mp-symbol">{t('manual.symbol')}</label>
          <input
            id="mp-symbol"
            value={symbol}
            placeholder="AAPL.US"
            autoComplete="off"
            onChange={(e) => setSymbol(e.target.value)}
            onFocus={() => setShowSuggestions(true)}
            // Delay so a click on a suggestion registers before the dropdown
            // closes — a plain onBlur would close it first and swallow the click.
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
          <label htmlFor="mp-qty">{t('manual.quantity')}</label>
          <input id="mp-qty" value={quantity} placeholder="10" onChange={(e) => setQuantity(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="mp-price">{t('manual.avgPrice')}</label>
          <input id="mp-price" value={price} placeholder="185.50" onChange={(e) => setPrice(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="mp-ccy">{t('manual.currency')}</label>
          <input id="mp-ccy" value={currency} placeholder="USD" onChange={(e) => setCurrency(e.target.value)} />
        </div>
        <button className="primary" disabled={!valid || busy} onClick={() => void submit()}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
        <button onClick={() => setOpen(false)}>{t('common.cancel')}</button>
      </div>

      <p className="muted" style={{ marginBottom: 0 }}>
        {t('manual.note')}
      </p>

      {error && (
        <div className="notice error" style={{ marginTop: '0.8rem', marginBottom: 0 }}>
          {error}
        </div>
      )}
    </div>
  )
}
