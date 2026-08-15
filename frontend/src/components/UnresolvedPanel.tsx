import { useState } from 'react'
import { api } from '../api/client'
import type { Instrument } from '../api/types'
import { useI18n } from '../i18n'
import { MappingCell } from './MappingCell'

interface Props {
  instruments: Instrument[]
  onUpdated: () => void
}

/**
 * Symbols with no provider mapping are shown explicitly: without a correction those
 * instruments stay outside every analysis. Leaving them silent would suggest the whole
 * portfolio is covered when it is not.
 *
 * Not every unresolved symbol is a real, correctable holding — a bad parse or a stray
 * manual entry can leave behind an instrument with nothing to fix it *to*. Deleting is
 * offered alongside correcting; the backend refuses it whenever the instrument still
 * has a position/lot/transaction attached, so this can never lose real portfolio data.
 */
export function UnresolvedPanel({ instruments, onUpdated }: Props) {
  const { t } = useI18n()
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (instruments.length === 0) return null

  async function remove(instrument: Instrument) {
    setBusyId(instrument.id)
    setError(null)
    try {
      await api.deleteInstrument(instrument.id)
      onUpdated()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="card">
      <h2>{t('unresolved.title', { count: instruments.length })}</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {t('unresolved.description')}
      </p>

      {error && (
        <div className="notice error" style={{ marginTop: '0.8rem', marginBottom: 0 }}>
          {error}
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('unresolved.brokerSymbol')}</th>
              <th>{t('unresolved.providerSymbol')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {instruments.map((instrument) => (
              <tr key={instrument.id}>
                <td>
                  <strong>{instrument.broker_symbol}</strong>
                </td>
                <td>
                  <MappingCell instrument={instrument} onUpdated={onUpdated} />
                </td>
                <td>
                  <button
                    className="link"
                    disabled={busyId === instrument.id}
                    onClick={() => void remove(instrument)}
                  >
                    {t('common.delete')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
