import { useState } from 'react'
import { useI18n } from '../i18n'

interface Props {
  title: string
  description: string
  label: string
  /** Runs the action and returns the one-line result to show next to it. */
  run: () => Promise<string>
}

/** One catch-up action on the "Data updates" tab: what it does, its button,
 * and the result of its last run. */
export function MaintenanceAction({ title, description, label, run }: Props) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  async function handleClick() {
    setBusy(true)
    setNotice(null)
    setFailed(false)
    try {
      setNotice(await run())
    } catch (err) {
      setFailed(true)
      setNotice(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="maintenance-action">
      <div>
        <h3 className="section-title">{title}</h3>
        <p className="muted">{description}</p>
        {notice && <p className={failed ? 'notice error' : 'muted'}>{notice}</p>}
      </div>
      <button onClick={() => void handleClick()} disabled={busy}>
        {busy ? t('common.running') : label}
      </button>
    </div>
  )
}
