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
 */
export function UnresolvedPanel({ instruments, onUpdated }: Props) {
  const { t } = useI18n()
  if (instruments.length === 0) return null

  return (
    <div className="card">
      <h2>{t('unresolved.title', { count: instruments.length })}</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {t('unresolved.description')}
      </p>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('unresolved.brokerSymbol')}</th>
              <th>{t('unresolved.providerSymbol')}</th>
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
