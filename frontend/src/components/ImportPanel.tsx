import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { ImportBatch, ImportPreview } from '../api/types'
import { useI18n } from '../i18n'

type BrokerKind = 'xtb' | 'mintos' | 'mintos-investments' | 'amundi' | 'amundi-synthese'

interface Props {
  kind: BrokerKind
  onImported: () => void
}

const ACCEPT_BY_KIND: Record<BrokerKind, string> = {
  xtb: '.xlsx,.xlsm,.csv',
  mintos: '.pdf',
  'mintos-investments': '.xlsx',
  amundi: '.pdf',
  'amundi-synthese': '.xlsb',
}

/**
 * Import a broker file — now a preview-then-confirm flow rather than an
 * immediate commit, plus a history of past imports with the ability to undo
 * the most recent one. See DEVLOG "Decision 3h.1" for why undo is restricted
 * to the newest import only. Shared across all three broker sources (XTB,
 * Mintos, Amundi) — see DEVLOG "Decision 3u.39".
 */
export function ImportPanel({ kind, onImported }: Props) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ImportBatch | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [history, setHistory] = useState<ImportBatch[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  function loadHistory() {
    api
      .listImports()
      .then(setHistory)
      .catch(() => setHistory([]))
  }

  useEffect(() => {
    loadHistory()
  }, [])

  async function runPreview(file: File) {
    setBusy(true)
    setError(null)
    setResult(null)
    setPreview(null)
    try {
      const report = await api.previewBrokerFile(kind, file)
      setPreview(report)
      setPendingFile(file)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function cancelPreview() {
    setPreview(null)
    setPendingFile(null)
  }

  async function confirmImport() {
    if (!pendingFile) return
    setBusy(true)
    setError(null)
    try {
      const batch = await api.importBrokerFile(kind, pendingFile)
      setResult(batch)
      setPreview(null)
      setPendingFile(null)
      onImported()
      loadHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function undo(importId: number) {
    setBusy(true)
    setError(null)
    try {
      await api.undoImport(importId)
      loadHistory()
      onImported()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h2>{t(`import.${kind}.title`)}</h2>

      <p className="muted" style={{ marginTop: 0 }}>
        {t(`import.${kind}.instructions`)}
      </p>
      <p className="muted">{t(`import.${kind}.multiAccount`)}</p>

      {!preview && (
        <div
          className={`dropzone${dragging ? ' dragging' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files?.[0]
            if (file) void runPreview(file)
          }}
        >
          <p style={{ margin: '0 0 0.7rem' }}>{t(`import.${kind}.dropzone`)}</p>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT_BY_KIND[kind]}
            style={{ display: 'none' }}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void runPreview(file)
              e.target.value = ''
            }}
          />
          <button className="primary" disabled={busy} onClick={() => inputRef.current?.click()}>
            {busy ? t('import.importing') : t('import.chooseFile')}
          </button>
        </div>
      )}

      {error && (
        <div className="notice error" style={{ marginTop: '1rem', marginBottom: 0 }}>
          {t('import.failed', { error })}
        </div>
      )}

      {preview && (
        <div style={{ marginTop: '1rem' }}>
          <p className="muted" style={{ marginTop: 0 }}>
            {t('import.previewTitle')}
          </p>
          <ImportReport batch={preview} />
          <div style={{ marginTop: '0.8rem', display: 'flex', gap: '0.6rem' }}>
            <button className="primary" disabled={busy} onClick={() => void confirmImport()}>
              {busy ? t('import.importing') : t('import.confirm')}
            </button>
            <button disabled={busy} onClick={cancelPreview}>
              {t('import.cancel')}
            </button>
          </div>
        </div>
      )}

      {result && <ImportReport batch={result} />}

      {history.length > 0 && (
        <details className="raw" style={{ marginTop: '1rem' }}>
          <summary>{t('import.historyTitle')}</summary>
          <ul>
            {history.map((batch, index) => (
              <li key={batch.id}>
                {t('import.historyLine', {
                  filename: batch.filename,
                  date: new Date(batch.imported_at).toLocaleDateString(),
                  positions: batch.positions_found,
                  transactions: batch.transactions_inserted,
                })}
                {index === 0 && (
                  <>
                    {' — '}
                    <button className="link" disabled={busy} onClick={() => void undo(batch.id)}>
                      {t('import.undo')}
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function ImportReport({ batch }: { batch: ImportBatch | ImportPreview }) {
  const { t } = useI18n()
  const nothingFound = batch.positions_found === 0 && batch.transactions_found === 0

  return (
    <div
      className={`notice ${nothingFound ? 'warning' : 'info'}`}
      style={{ marginTop: '1rem', marginBottom: 0 }}
    >
      {t('import.summary', {
        filename: batch.filename,
        positions: batch.positions_found,
        transactions: batch.transactions_found,
        inserted: batch.transactions_inserted,
      })}

      {batch.warnings.length > 0 && (
        <ul>
          {batch.warnings.map((warning, index) => (
            // Warnings arrive as {code, params}: the backend stays language-neutral
            // and the wording is chosen here, in the user's language.
            <li key={index}>{t(warning.code, warning.params)}</li>
          ))}
        </ul>
      )}

      {batch.sections.length > 0 && (
        <details className="raw" style={{ marginTop: '0.6rem' }}>
          <summary>{t('import.sectionsTitle')}</summary>
          <ul>
            {batch.sections.map((section, index) => (
              <li key={index}>
                {t('import.sectionLine', {
                  sheet: section.sheet,
                  count: section.count,
                  kind: t(`section.${section.kind}`),
                  rows: section.source_rows,
                })}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
