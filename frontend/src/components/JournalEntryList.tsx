import { useState } from 'react'
import type { JournalEntry } from '../api/types'
import { useI18n } from '../i18n'

interface Props {
  entries: JournalEntry[]
  onUpdate: (id: number, payload: { thesis: string; review_date: string | null }) => Promise<void>
  onUpdateOutcome: (id: number, payload: { outcome_note: string | null }) => Promise<void>
  onDelete: (id: number) => void
}

function isDueForReview(entry: JournalEntry): boolean {
  return entry.review_date !== null && entry.outcome_note === null && entry.review_date <= new Date().toISOString().slice(0, 10)
}

export function JournalEntryList({ entries, onUpdate, onUpdateOutcome, onDelete }: Props) {
  const { t, formatDate } = useI18n()
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState({ thesis: '', reviewDate: '' })
  const [outcomeEditingId, setOutcomeEditingId] = useState<number | null>(null)
  const [outcomeDraft, setOutcomeDraft] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  function startEdit(entry: JournalEntry) {
    setEditingId(entry.id)
    setEditDraft({ thesis: entry.thesis, reviewDate: entry.review_date ?? '' })
    setError(null)
  }

  function cancelEdit() {
    setEditingId(null)
    setError(null)
  }

  async function saveEdit(id: number) {
    if (!editDraft.thesis.trim()) return
    setBusyId(id)
    setError(null)
    try {
      await onUpdate(id, { thesis: editDraft.thesis.trim(), review_date: editDraft.reviewDate.trim() || null })
      setEditingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  function startOutcome(entry: JournalEntry) {
    setOutcomeEditingId(entry.id)
    setOutcomeDraft(entry.outcome_note ?? '')
    setError(null)
  }

  function cancelOutcome() {
    setOutcomeEditingId(null)
    setError(null)
  }

  async function saveOutcome(id: number) {
    setBusyId(id)
    setError(null)
    try {
      await onUpdateOutcome(id, { outcome_note: outcomeDraft.trim() || null })
      setOutcomeEditingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  if (entries.length === 0) {
    return <div className="empty">{t('journal.empty')}</div>
  }

  return (
    <>
      {error && <div className="notice error">{error}</div>}

      {entries.map((entry) => (
        <div className="card" key={entry.id}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0 }}>{entry.instrument ? entry.instrument.broker_symbol : t('journal.general')}</h3>
            {isDueForReview(entry) && <span className="tag confidence-review">{t('journal.dueForReview')}</span>}
            <span className="muted" style={{ fontSize: '0.85rem' }}>
              {t('journal.entryDate')}: {formatDate(entry.entry_date)}
            </span>
            {entry.review_date && (
              <span className="muted" style={{ fontSize: '0.85rem' }}>
                {t('journal.reviewDate')}: {formatDate(entry.review_date)}
              </span>
            )}
          </div>

          {editingId === entry.id ? (
            <div style={{ marginTop: '0.6rem' }}>
              <textarea
                rows={4}
                style={{ width: '100%' }}
                value={editDraft.thesis}
                onChange={(e) => setEditDraft({ ...editDraft, thesis: e.target.value })}
              />
              <div className="field" style={{ marginTop: '0.4rem', maxWidth: '12rem' }}>
                <label htmlFor={`journal-edit-review-${entry.id}`}>{t('journal.form.reviewDate')}</label>
                <input
                  id={`journal-edit-review-${entry.id}`}
                  type="date"
                  value={editDraft.reviewDate}
                  onChange={(e) => setEditDraft({ ...editDraft, reviewDate: e.target.value })}
                />
              </div>
              <div style={{ marginTop: '0.4rem' }}>
                <button className="link" disabled={busyId === entry.id} onClick={() => void saveEdit(entry.id)}>
                  {busyId === entry.id ? t('common.saving') : t('common.save')}
                </button>{' '}
                <button className="link" disabled={busyId === entry.id} onClick={cancelEdit}>
                  {t('common.cancel')}
                </button>
              </div>
            </div>
          ) : (
            <p style={{ whiteSpace: 'pre-wrap', marginTop: '0.6rem' }}>{entry.thesis}</p>
          )}

          {outcomeEditingId === entry.id ? (
            <div style={{ marginTop: '0.6rem' }}>
              <label htmlFor={`journal-outcome-${entry.id}`}>{t('journal.outcome.title')}</label>
              <textarea
                id={`journal-outcome-${entry.id}`}
                rows={3}
                style={{ width: '100%' }}
                value={outcomeDraft}
                onChange={(e) => setOutcomeDraft(e.target.value)}
              />
              <div style={{ marginTop: '0.4rem' }}>
                <button className="link" disabled={busyId === entry.id} onClick={() => void saveOutcome(entry.id)}>
                  {busyId === entry.id ? t('common.saving') : t('journal.outcome.save')}
                </button>{' '}
                <button className="link" disabled={busyId === entry.id} onClick={cancelOutcome}>
                  {t('common.cancel')}
                </button>
              </div>
            </div>
          ) : (
            entry.outcome_note && (
              <div style={{ marginTop: '0.6rem' }}>
                <strong>{t('journal.outcome.title')}</strong>
                <p style={{ whiteSpace: 'pre-wrap', margin: '0.2rem 0 0' }}>{entry.outcome_note}</p>
              </div>
            )
          )}

          {editingId !== entry.id && outcomeEditingId !== entry.id && (
            <div style={{ marginTop: '0.6rem' }}>
              <button className="link" onClick={() => startEdit(entry)}>
                {t('common.edit')}
              </button>{' '}
              <button className="link" onClick={() => startOutcome(entry)}>
                {entry.outcome_note ? t('journal.outcome.title') : t('journal.outcome.add')}
              </button>{' '}
              <button className="link" onClick={() => onDelete(entry.id)}>
                {t('common.delete')}
              </button>
            </div>
          )}
        </div>
      ))}
    </>
  )
}
