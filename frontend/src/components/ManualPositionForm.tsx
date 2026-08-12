import { useState } from 'react'
import { api } from '../api/client'

interface Props {
  onCreated: () => void
}

export function ManualPositionForm({ onCreated }: Props) {
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [currency, setCurrency] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
          <div>
            <h2 style={{ marginBottom: '0.2rem' }}>Position saisie manuellement</h2>
            <span className="muted">
              Pour un titre absent de l'export, ou détenu chez un autre courtier.
            </span>
          </div>
          <button onClick={() => setOpen(true)}>Ajouter</button>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <h2>Nouvelle position</h2>

      <div className="form-row">
        <div className="field">
          <label htmlFor="mp-symbol">Symbole XTB</label>
          <input
            id="mp-symbol"
            value={symbol}
            placeholder="AAPL.US"
            onChange={(e) => setSymbol(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="mp-qty">Quantité</label>
          <input id="mp-qty" value={quantity} placeholder="10" onChange={(e) => setQuantity(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="mp-price">Prix de revient</label>
          <input id="mp-price" value={price} placeholder="185,50" onChange={(e) => setPrice(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="mp-ccy">Devise</label>
          <input id="mp-ccy" value={currency} placeholder="USD" onChange={(e) => setCurrency(e.target.value)} />
        </div>
        <button className="primary" disabled={!valid || busy} onClick={() => void submit()}>
          {busy ? 'Ajout…' : 'Enregistrer'}
        </button>
        <button onClick={() => setOpen(false)}>Annuler</button>
      </div>

      <p className="muted" style={{ marginBottom: 0 }}>
        Une position manuelle n'a pas de valorisation fournie par le courtier&nbsp;: elle ne
        comptera pas dans les totaux tant que les cours de marché ne sont pas branchés.
      </p>

      {error && (
        <div className="notice error" style={{ marginTop: '0.8rem', marginBottom: 0 }}>
          {error}
        </div>
      )}
    </div>
  )
}
