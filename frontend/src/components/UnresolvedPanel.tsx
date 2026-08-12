import type { Instrument } from '../api/types'
import { MappingCell } from './MappingCell'

interface Props {
  instruments: Instrument[]
  onUpdated: () => void
}

/**
 * Les symboles sans correspondance fournisseur sont affichés explicitement :
 * sans correction, ces titres resteront hors de toute analyse. Les laisser
 * silencieux donnerait l'illusion d'un portefeuille entièrement couvert.
 */
export function UnresolvedPanel({ instruments, onUpdated }: Props) {
  if (instruments.length === 0) return null

  return (
    <div className="card">
      <h2>Symboles sans correspondance ({instruments.length})</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Ces instruments n'ont pas de correspondance automatique chez les fournisseurs de
        données&nbsp;: tant qu'ils ne sont pas corrigés, ils ne seront pas analysés. Les CFD sur
        indices, matières premières et devises n'ont pas de données fondamentales&nbsp;— il est
        normal qu'ils restent sans correspondance.
      </p>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbole XTB</th>
              <th>Symbole fournisseur (format Yahoo)</th>
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
