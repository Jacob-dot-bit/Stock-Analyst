import { useRef, useState } from 'react'
import { api } from '../api/client'
import type { ImportBatch } from '../api/types'
import { useI18n } from '../i18n'

interface Props {
  onImported: () => void
}

export function ImportPanel({ onImported }: Props) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ImportBatch | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  async function upload(file: File) {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await api.importXtbFile(file))
      onImported()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h2>{t('import.title')}</h2>

      <p className="muted" style={{ marginTop: 0 }}>
        {t('import.instructions')}
      </p>
      <p className="muted">{t('import.multiAccount')}</p>

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
          if (file) void upload(file)
        }}
      >
        <p style={{ margin: '0 0 0.7rem' }}>{t('import.dropzone')}</p>
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xlsm,.csv"
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void upload(file)
            e.target.value = ''
          }}
        />
        <button className="primary" disabled={busy} onClick={() => inputRef.current?.click()}>
          {busy ? t('import.importing') : t('import.chooseFile')}
        </button>
      </div>

      {error && (
        <div className="notice error" style={{ marginTop: '1rem', marginBottom: 0 }}>
          {t('import.failed', { error })}
        </div>
      )}

      {result && <ImportReport batch={result} />}
    </div>
  )
}

function ImportReport({ batch }: { batch: ImportBatch }) {
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
