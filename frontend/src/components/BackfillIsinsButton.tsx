import { useState } from 'react'
import { api } from '../api/client'
import { useI18n } from '../i18n'

interface Props {
  onDone?: () => void
}

/**
 * One-off catch-up trigger for `symbols/duplicates.py::backfill_isins` —
 * resolves an ISIN for every held/watchlisted/screened instrument that
 * already has a company name on file but never had its ISIN looked up
 * (e.g. a position re-tracked on the watchlist after being fully sold, or
 * anything added before ISIN duplicate detection existed). Shared between
 * the Watchlist and Screener pages since it isn't scoped to either one.
 */
export function BackfillIsinsButton({ onDone }: Props) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  async function handleClick() {
    setBusy(true)
    setNotice(null)
    try {
      const result = await api.backfillIsins()
      setNotice(t('duplicates.backfillResult', { checked: result.checked, updated: result.updated }))
      onDone?.()
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
      <button onClick={() => void handleClick()} disabled={busy}>
        {busy ? t('duplicates.backfilling') : t('duplicates.backfillIsins')}
      </button>
      {notice && <span className="muted">{notice}</span>}
    </span>
  )
}
