import { useRef, useState } from 'react'
import { api } from '../api/client'
import type { ImportBatch } from '../api/types'

interface Props {
  onImported: () => void
}

export function ImportPanel({ onImported }: Props) {
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
      <h2>Importer un relevé XTB</h2>

      <p className="muted" style={{ marginTop: 0 }}>
        Dans xStation&nbsp;: <strong>Account history</strong> → <strong>Export</strong> → période
        «&nbsp;All&nbsp;», type <strong>Full report</strong>, format <strong>Excel</strong>.
        L'API XTB ayant été fermée le 14&nbsp;mars&nbsp;2025, l'export de fichier est le seul moyen
        fiable de récupérer vos positions. Aucun identifiant n'est demandé ni stocké.
      </p>

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
        <p style={{ margin: '0 0 0.7rem' }}>
          Glissez le fichier ici, ou choisissez-le manuellement (.xlsx ou .csv)
        </p>
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
          {busy ? 'Import en cours…' : 'Choisir un fichier'}
        </button>
      </div>

      {error && (
        <div className="notice error" style={{ marginTop: '1rem', marginBottom: 0 }}>
          Échec de l'import&nbsp;: {error}
        </div>
      )}

      {result && <ImportReport batch={result} />}
    </div>
  )
}

function ImportReport({ batch }: { batch: ImportBatch }) {
  const nothingFound = batch.positions_found === 0 && batch.transactions_found === 0

  return (
    <div className={`notice ${nothingFound ? 'warning' : 'info'}`} style={{ marginTop: '1rem', marginBottom: 0 }}>
      <strong>{batch.filename}</strong> — {batch.positions_found} position(s) ouverte(s),{' '}
      {batch.transactions_found} opération(s) détectée(s), dont {batch.transactions_inserted}{' '}
      nouvelle(s) en base.

      {batch.warnings.length > 0 && (
        <ul>
          {batch.warnings.map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
        </ul>
      )}

      {batch.detected_sections.length > 0 && (
        <details className="raw" style={{ marginTop: '0.6rem' }}>
          <summary>Sections détectées dans le fichier</summary>
          <ul>
            {batch.detected_sections.map((section, index) => (
              <li key={index}>{section}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
