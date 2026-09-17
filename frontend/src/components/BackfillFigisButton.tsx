import { useState } from 'react'
import { api } from '../api/client'
import { useI18n } from '../i18n'

interface Props {
  onDone?: () => void
}

/**
 * One-off catch-up trigger for `symbols/duplicates.py::backfill_figis` —
 * resolves an OpenFIGI canonical identity for every held/watchlisted/
 * screened instrument that doesn't have one yet, so
 * `find_figi_duplicates` (surfaced on Data Health) can spot the same real
 * company tracked under two different broker symbols. Shared between the
 * Watchlist and Screener pages, same convention as `BackfillIsinsButton`.
 * See DEVLOG "Decision 3u.76".
 */
export function BackfillFigisButton({ onDone }: Props) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  async function handleClick() {
    setBusy(true)
    setNotice(null)
    try {
      const result = await api.backfillFigis()
      setNotice(
        result.remaining > 0
          ? t('duplicates.backfillFigisResultMore', { checked: result.checked, remaining: result.remaining })
          : t('duplicates.backfillFigisResultDone', { checked: result.checked }),
      )
      onDone?.()
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
      <button onClick={() => void handleClick()} disabled={busy}>
        {busy ? t('duplicates.backfilling') : t('duplicates.backfillFigis')}
      </button>
      {notice && (
        <span className="muted" style={{ fontSize: '0.82rem' }}>
          {notice}
        </span>
      )}
    </span>
  )
}
