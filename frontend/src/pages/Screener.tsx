import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Score, ScreenerCandidate } from '../api/types'
import { AddToScreenerForm } from '../components/AddToScreenerForm'
import { BackfillIsinsButton } from '../components/BackfillIsinsButton'
import { DiscoveryPanel } from '../components/DiscoveryPanel'
import { ScreenerTable } from '../components/ScreenerTable'
import { useI18n } from '../i18n'

export function Screener() {
  const { t } = useI18n()
  const [items, setItems] = useState<ScreenerCandidate[]>([])
  const [sparklines, setSparklines] = useState<Record<number, number[]>>({})
  const [scores, setScores] = useState<Record<number, Score>>({})
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // Shared with both `ScreenerTable` and `DiscoveryPanel` below — one price
  // filter for every "hidden gems" list on this page, not a separate
  // control per list (user-requested: "un moyen qu'on puisse filtrer tous
  // les titres d'un coup"). See DEVLOG "Decision 3u.54"/"Step 3u.55".
  const [priceMin, setPriceMin] = useState('')
  const [priceMax, setPriceMax] = useState('')

  const loadSparklines = useCallback(async () => {
    const series = await api.getScreenerSparklines()
    setSparklines(Object.fromEntries(series.map((s) => [s.instrument_id, s.closes])))
  }, [])

  const loadScores = useCallback(async () => {
    const list = await api.getScreenerScores()
    setScores(Object.fromEntries(list.map((s) => [s.instrument_id, s])))
  }, [])

  const load = useCallback(async () => {
    setError(null)
    try {
      const [list] = await Promise.all([api.getScreenerCandidates(), loadSparklines(), loadScores()])
      setItems(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [loadSparklines, loadScores])

  useEffect(() => {
    void load()
  }, [load])

  async function handleDelete(id: number) {
    try {
      await api.deleteScreenerCandidate(id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleUpdate(id: number, payload: { company_name: string | null }) {
    const updated = await api.updateScreenerCandidate(id, payload)
    await load()
    return { duplicate_warning: updated.duplicate_warning }
  }

  return (
    <>
      <div className="page-header">
        <h1>{t('gems.title')}</h1>
        <p>{t('gems.description')}</p>
        <BackfillIsinsButton onDone={() => void load()} />
      </div>

      {error && <div className="notice error">{error}</div>}

      <div className="card">
        <h2>{t('gems.priceFilterTitle')}</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          {t('gems.priceFilterHint')}
        </p>
        <div className="form-row">
          <div className="field">
            <label htmlFor="gems-price-min">{t('filters.priceMin')}</label>
            <input
              id="gems-price-min"
              type="number"
              inputMode="decimal"
              value={priceMin}
              onChange={(e) => setPriceMin(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="gems-price-max">{t('filters.priceMax')}</label>
            <input
              id="gems-price-max"
              type="number"
              inputMode="decimal"
              value={priceMax}
              onChange={(e) => setPriceMax(e.target.value)}
            />
          </div>
        </div>
      </div>

      <AddToScreenerForm onCreated={() => void load()} />

      <div className="card">
        <h2>{t('gems.candidates')}</h2>
        {loading ? (
          <div className="empty">{t('common.loading')}</div>
        ) : (
          <ScreenerTable
            items={items}
            sparklines={sparklines}
            scores={scores}
            onDelete={(id) => void handleDelete(id)}
            onUpdate={handleUpdate}
            priceMin={priceMin}
            priceMax={priceMax}
          />
        )}
      </div>

      <DiscoveryPanel onAdded={() => void load()} priceMin={priceMin} priceMax={priceMax} />
    </>
  )
}
