import { useState } from 'react'
import { api } from '../api/client'
import type { Instrument } from '../api/types'

interface Props {
  instrument: Instrument
  onUpdated: () => void
}

/**
 * Affiche la correspondance symbole courtier → symbole fournisseur, et permet de la
 * corriger sur place.
 *
 * La conversion automatique ne transforme que le suffixe de place, jamais la racine
 * du symbole : « ERICB.SE » devient « ERICB.ST » alors que Yahoo attend « ERIC-B.ST ».
 * Une correspondance automatique est donc présentée comme *non vérifiée* et non comme
 * validée — l'afficher en vert donnerait une assurance que rien ne justifie.
 */
export function MappingCell({ instrument, onUpdated }: Props) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(instrument.provider_symbol ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    if (!value.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.setSymbolOverride({
        broker_symbol: instrument.broker_symbol,
        provider_symbol: value.trim(),
      })
      setEditing(false)
      onUpdated()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center' }}>
        <input
          autoFocus
          value={value}
          placeholder="ex. ERIC-B.ST"
          style={{ width: 130 }}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void save()
            if (e.key === 'Escape') setEditing(false)
          }}
        />
        <button disabled={busy || !value.trim()} onClick={() => void save()}>
          {busy ? '…' : 'OK'}
        </button>
        <button className="link" onClick={() => setEditing(false)}>
          Annuler
        </button>
        {error && <span style={{ color: 'var(--negative)', fontSize: '0.78rem' }}>{error}</span>}
      </div>
    )
  }

  const { provider_symbol, mapping_status } = instrument

  return (
    <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
      {provider_symbol ? <code>{provider_symbol}</code> : null}

      {mapping_status === 'MANUAL' && <span className="tag manual">confirmée</span>}

      {mapping_status === 'RESOLVED' && (
        <span
          className="tag neutral"
          title="Conversion automatique du suffixe de place. La racine du symbole n'a pas été vérifiée auprès d'un fournisseur."
        >
          non vérifiée
        </span>
      )}

      {mapping_status === 'UNRESOLVED' && <span className="tag unresolved">à corriger</span>}

      <button className="link" onClick={() => setEditing(true)}>
        corriger
      </button>
    </div>
  )
}
