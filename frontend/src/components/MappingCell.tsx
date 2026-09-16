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
  const { t, formatDate } = useI18n()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(instrument.provider_symbol ?? '')
  const [isin, setIsin] = useState(instrument.isin ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      // Two independent identifiers: the provider symbol drives Yahoo and Twelve
      // Data, the ISIN drives the European source. Either may be set alone.
      if (value.trim() && value.trim() !== instrument.provider_symbol) {
        await api.setSymbolOverride({
          broker_symbol: instrument.broker_symbol,
          provider_symbol: value.trim(),
        })
      }
      if (isin.trim() && isin.trim().toUpperCase() !== instrument.isin) {
        await api.setIsin({ broker_symbol: instrument.broker_symbol, isin: isin.trim() })
      }
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
      <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          autoFocus
          value={value}
          placeholder={t('mapping.placeholder')}
          style={{ width: 120 }}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void save()
            if (e.key === 'Escape') setEditing(false)
          }}
        />
        <input
          value={isin}
          placeholder={t('mapping.isinPlaceholder')}
          title={t('mapping.isinHelp')}
          style={{ width: 130 }}
          onChange={(e) => setIsin(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void save()
            if (e.key === 'Escape') setEditing(false)
          }}
        />
        <button disabled={busy || (!value.trim() && !isin.trim())} onClick={() => void save()}>
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

  // Structurally never priceable (CFD, corporate-action residual, P2P
  // aggregate, employee-savings fund) — there is no ticker to look up, so
  // "needs fixing" would send the user hunting for nothing. Same exclusion
  // as `_unresolved_instruments()` on the backend. See DEVLOG "Decision 3u.39".
  if (instrument.not_priceable_reason) {
    return provider_symbol ? <code>{provider_symbol}</code> : <span className="muted">{t('common.notApplicable')}</span>
  }

  return (
    <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
      {provider_symbol ? <code>{provider_symbol}</code> : null}

      {mapping_status === 'MANUAL' && <span className="tag manual">{t('mapping.confirmed')}</span>}

      {/* Verified means a provider actually returned data for this symbol — the only
          real proof the mapping is right, as opposed to merely plausible. */}
      {instrument.verified_at && (
        <span
          className="tag confidence-confirmed"
          title={t('mapping.verifiedTooltip', {
            date: formatDate(instrument.verified_at),
            provider: instrument.verified_provider ?? '?',
          })}
        >
          {t('mapping.verified')}
        </span>
      )}

      {mapping_status === 'RESOLVED' && !instrument.verified_at && (
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
