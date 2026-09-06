import type { ApiMessage, Instrument } from '../api/types'
import { useI18n } from '../i18n'

const STATUS_ICON: Record<string, string> = {
  fresh: '✓',
  stale: '⏱',
  error: '❌',
  not_priceable: '🚫',
  unmapped: '⚠',
  declared: '🗓',
}

export function PriceStatusBadge({
  instrument,
  valuationNote,
}: {
  instrument: Instrument
  /** Overrides the generic 'not_priceable' 🚫 for a Mintos/Amundi position
   * that has a declared value with a known date — see `Position.valuation_note`
   * and DEVLOG "Decision 3u.50". `undefined`/`null` falls back to the plain
   * `instrument.price_status` badge below. */
  valuationNote?: ApiMessage | null
}) {
  const { t, formatDate } = useI18n()

  if (valuationNote) {
    const stale = valuationNote.code === 'valuation.declaredStale'
    return (
      <span
        className={`price-status price-status-${stale ? 'stale' : 'fresh'}`}
        title={t(valuationNote.code, valuationNote.params)}
      >
        {STATUS_ICON.declared}
      </span>
    )
  }

  const status = instrument.price_status
  if (!status) return null

  let title = t(`priceStatus.${status}`)
  if ((status === 'fresh' || status === 'stale') && instrument.verified_provider) {
    title = t('priceStatus.viaProvider', {
      provider: instrument.verified_provider,
      date: instrument.verified_at ? formatDate(instrument.verified_at) : '',
    })
  }

  return (
    <span className={`price-status price-status-${status}`} title={title}>
      {STATUS_ICON[status]}
    </span>
  )
}
