import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { SymbolSearchResult } from '../api/types'

//: Avoids firing a request (and spending FMP's quota) on every character typed.
const SEARCH_DEBOUNCE_MS = 350

interface Props {
  id: string
  label: string
  value: string
  onChange: (symbol: string) => void
  /** Called with the picked company, after `onChange` got its symbol — for a
   * form that also fills in the company name. */
  onPick?: (result: SymbolSearchResult) => void
}

/**
 * The symbol field of every "add" form (manual position, watchlist, gems,
 * journal): typing a company name suggests matching US tickers.
 *
 * Best-effort: if FMP has no key configured (400) or the search otherwise
 * fails, suggestions just stay empty rather than surfacing an error — typing
 * the symbol directly still works fine.
 */
export function SymbolInput({ id, label, value, onChange, onPick }: Props) {
  const [suggestions, setSuggestions] = useState<SymbolSearchResult[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const query = value.trim()
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
  }, [value])

  function pick(result: SymbolSearchResult) {
    // FMP's free tier only covers US listings, so the suggested symbol is
    // always a US ticker — append the broker-style ".US" suffix this app's
    // symbol resolution expects (see symbols/mapping.py).
    onChange(`${result.symbol}.US`)
    onPick?.(result)
    setShowSuggestions(false)
    setSuggestions([])
  }

  return (
    <div className="field" style={{ position: 'relative' }}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        value={value}
        placeholder="AAPL.US"
        autoComplete="off"
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setShowSuggestions(true)}
        // Delay so a click on a suggestion registers before the dropdown
        // closes — a plain onBlur would close it first and swallow the click.
        onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
      />
      {showSuggestions && suggestions.length > 0 && (
        <ul className="symbol-suggestions">
          {suggestions.map((s) => (
            <li key={s.symbol}>
              <button type="button" onClick={() => pick(s)}>
                <strong>{s.symbol}</strong> <span className="muted">{s.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
