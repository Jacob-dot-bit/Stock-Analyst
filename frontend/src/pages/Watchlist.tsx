import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Score, WatchlistItem, WatchlistSignal } from '../api/types'
import { AddToWatchlistForm } from '../components/AddToWatchlistForm'
import { BackfillIsinsButton } from '../components/BackfillIsinsButton'
import { WatchlistTable } from '../components/WatchlistTable'
import { useI18n } from '../i18n'

export function Watchlist() {
  const { t } = useI18n()
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [sparklines, setSparklines] = useState<Record<number, number[]>>({})
  const [scores, setScores] = useState<Record<number, Score>>({})
  const [signals, setSignals] = useState<Record<number, WatchlistSignal>>({})
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const loadSparklines = useCallback(async () => {
    const series = await api.getWatchlistSparklines()
    setSparklines(Object.fromEntries(series.map((s) => [s.instrument_id, s.closes])))
  }, [])

  const loadScores = useCallback(async () => {
    const list = await api.getWatchlistScores()
    setScores(Object.fromEntries(list.map((s) => [s.instrument_id, s])))
  }, [])

  const loadSignals = useCallback(async () => {
    const list = await api.getWatchlistSignals()
    setSignals(Object.fromEntries(list.map((s) => [s.instrument_id, s])))
  }, [])

  const load = useCallback(async () => {
    setError(null)
    try {
      const [list] = await Promise.all([api.getWatchlist(), loadSparklines(), loadScores(), loadSignals()])
      setItems(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [loadSparklines, loadScores, loadSignals])

  useEffect(() => {
    void load()
  }, [load])

  async function handleDelete(id: number) {
    try {
      await api.deleteWatchlistItem(id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleUpdate(
    id: number,
    payload: { target_entry_price: number | null; note: string | null; company_name: string | null },
  ) {
    const updated = await api.updateWatchlistItem(id, payload)
    await load()
    return { duplicate_warning: updated.duplicate_warning }
  }

  return (
    <>
      <div className="page-header">
        <h1>{t('watchlist.title')}</h1>
        <p>{t('watchlist.description')}</p>
        <BackfillIsinsButton onDone={() => void load()} />
      </div>

      {error && <div className="notice error">{error}</div>}

      <AddToWatchlistForm onCreated={() => void load()} />

      <div className="card">
        <h2>{t('watchlist.openItems')}</h2>
        {loading ? (
          <div className="empty">{t('common.loading')}</div>
        ) : (
          <WatchlistTable
            items={items}
            sparklines={sparklines}
            scores={scores}
            signals={signals}
            onDelete={(id) => void handleDelete(id)}
            onUpdate={handleUpdate}
          />
        )}
      </div>
    </>
  )
}
