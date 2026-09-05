import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Backup } from '../api/types'
import { useI18n } from '../i18n'

function formatSize(bytes: number): string {
  const mb = bytes / (1024 * 1024)
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(0)} KB`
}

/**
 * Manual backup/restore for the local SQLite file — the app's only source
 * of truth, with no server-side redundancy at all before this. A backup is
 * a plain timestamped file copy; restore requires typing the exact
 * filename before it's enabled, since it overwrites the live database with
 * no undo. See DEVLOG "Decision 3u.29".
 */
export function BackupPanel() {
  const { t, locale, formatDate } = useI18n()
  const [backups, setBackups] = useState<Backup[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmTarget, setConfirmTarget] = useState<string | null>(null)
  const [confirmText, setConfirmText] = useState('')

  function load() {
    api.getBackups().then(setBackups).catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(load, [])

  async function handleCreate() {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const backup = await api.createBackup()
      setNotice(t('backup.created', { filename: backup.filename }))
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function startRestore(filename: string) {
    setConfirmTarget(filename)
    setConfirmText('')
    setError(null)
    setNotice(null)
  }

  function cancelRestore() {
    setConfirmTarget(null)
    setConfirmText('')
  }

  async function handleRestore(filename: string) {
    setBusy(true)
    setError(null)
    try {
      await api.restoreBackup(filename)
      setNotice(t('backup.restored', { filename }))
      setConfirmTarget(null)
      setConfirmText('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function formatDateTime(iso: string): string {
    const date = new Date(iso)
    return Number.isNaN(date.getTime()) ? formatDate(iso) : date.toLocaleString(locale)
  }

  return (
    <div className="card">
      <h2>{t('backup.title')}</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {t('backup.description')}
      </p>

      {error && <div className="notice error">{error}</div>}
      {notice && <div className="notice success">{notice}</div>}

      <button className="primary" onClick={() => void handleCreate()} disabled={busy}>
        {busy ? t('common.saving') : t('backup.create')}
      </button>

      {backups && backups.length === 0 && <div className="empty">{t('backup.empty')}</div>}

      {backups && backups.length > 0 && (
        <div className="table-wrap" style={{ marginTop: '1rem' }}>
          <table>
            <thead>
              <tr>
                <th>{t('backup.date')}</th>
                <th className="num">{t('backup.size')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {backups.map((backup) => (
                <tr key={backup.filename}>
                  <td>{formatDateTime(backup.created_at)}</td>
                  <td className="num">{formatSize(backup.size_bytes)}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {confirmTarget === backup.filename ? (
                      <span style={{ display: 'inline-flex', gap: '0.4rem', alignItems: 'center' }}>
                        <input
                          style={{ width: '14rem' }}
                          placeholder={backup.filename}
                          value={confirmText}
                          onChange={(e) => setConfirmText(e.target.value)}
                        />
                        <button
                          className="link"
                          disabled={busy || confirmText !== backup.filename}
                          onClick={() => void handleRestore(backup.filename)}
                        >
                          {t('backup.confirmRestore')}
                        </button>
                        <button className="link" disabled={busy} onClick={cancelRestore}>
                          {t('common.cancel')}
                        </button>
                      </span>
                    ) : (
                      <button className="link" onClick={() => startRestore(backup.filename)}>
                        {t('backup.restore')}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {confirmTarget && <p className="muted" style={{ fontSize: '0.85rem' }}>{t('backup.restoreWarning')}</p>}
        </div>
      )}
    </div>
  )
}
