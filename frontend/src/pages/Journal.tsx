import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { JournalEntry } from '../api/types'
import { AddJournalEntryForm } from '../components/AddJournalEntryForm'
import { JournalEntryList } from '../components/JournalEntryList'
import { useI18n } from '../i18n'

export function Journal() {
  const { t } = useI18n()
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setError(null)
    try {
      setEntries(await api.getJournalEntries())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function handleDelete(id: number) {
    try {
      await api.deleteJournalEntry(id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleUpdate(id: number, payload: { thesis: string; review_date: string | null }) {
    await api.updateJournalEntry(id, payload)
    await load()
  }

  async function handleUpdateOutcome(id: number, payload: { outcome_note: string | null }) {
    await api.updateJournalEntryOutcome(id, payload)
    await load()
  }

  return (
    <>
      <div className="page-header">
        <h1>{t('journal.title')}</h1>
        <p>{t('journal.subtitle')}</p>
      </div>

      {error && <div className="notice error">{error}</div>}

      <AddJournalEntryForm onCreated={() => void load()} />

      {loading ? (
        <div className="empty">{t('common.loading')}</div>
      ) : (
        <JournalEntryList
          entries={entries}
          onUpdate={handleUpdate}
          onUpdateOutcome={handleUpdateOutcome}
          onDelete={(id) => void handleDelete(id)}
        />
      )}
    </>
  )
}
