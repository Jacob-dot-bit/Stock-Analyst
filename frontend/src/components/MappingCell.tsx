import { useState } from 'react'
import { api } from '../api/client'
import type { Instrument } from '../api/types'
import { useI18n } from '../i18n'

interface Props {
  instrument: Instrument
  onUpdated: () => void
}

/**
 * Shows the broker-symbol → provider-symbol mapping, and lets it be fixed in place.
 *
 * Automatic conversion only rewrites the listing suffix, never the root of the
 * symbol: "ERICB.SE" becomes "ERICB.ST" where Yahoo expects "ERIC-B.ST". An automatic
 * mapping is therefore shown as *unverified* rather than validated — displaying it in
 * green would imply a confidence nothing supports.
 */
export function MappingCell({ instrument, onUpdated }: Props) {
  const { t } = useI18n()
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
          placeholder={t('mapping.placeholder')}
          style={{ width: 130 }}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void save()
            if (e.key === 'Escape') setEditing(false)
          }}
        />
        <button disabled={busy || !value.trim()} onClick={() => void save()}>
          {busy ? '…' : t('common.ok')}
        </button>
        <button className="link" onClick={() => setEditing(false)}>
          {t('common.cancel')}
        </button>
        {error && <span style={{ color: 'var(--negative)', fontSize: '0.78rem' }}>{error}</span>}
      </div>
    )
  }

  const { provider_symbol, mapping_status } = instrument

  return (
    <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
      {provider_symbol ? <code>{provider_symbol}</code> : null}

      {mapping_status === 'MANUAL' && <span className="tag manual">{t('mapping.confirmed')}</span>}

      {mapping_status === 'RESOLVED' && (
        <span className="tag neutral" title={t('mapping.unverifiedTooltip')}>
          {t('mapping.unverified')}
        </span>
      )}

      {mapping_status === 'UNRESOLVED' && <span className="tag unresolved">{t('mapping.toFix')}</span>}

      <button className="link" onClick={() => setEditing(true)}>
        {t('mapping.fix')}
      </button>
    </div>
  )
}
