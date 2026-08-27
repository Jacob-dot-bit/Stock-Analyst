import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { api } from '../api/client'
import { useI18n } from '../i18n'

//: Cache-only read (GET /api/watchlist never fetches) polled while the app
//: is open — this is an in-app-only signal, no background job and no push:
//: it only ever reflects prices as fresh as the last refresh.
const POLL_INTERVAL_MS = 60_000

/** A count of watchlist items currently at or below their target price,
 * shown as a small badge in the top nav — the only way, besides opening the
 * Watchlist page itself, to notice a target has been reached. Deliberately
 * simpler than the table's own "opportunity" highlighting (which also
 * requires a high score): this counts a target hit on price alone, since
 * that's the literal thing being alerted on. */
export function AlertsBell() {
  const { t } = useI18n()
  const [count, setCount] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function check() {
      try {
        const items = await api.getWatchlist()
        if (cancelled) return
        setCount(items.filter((i) => i.distance_to_target_pct !== null && i.distance_to_target_pct <= 0).length)
      } catch {
        // A failed check just leaves the previous count showing — no error
        // banner belongs in the nav bar.
      }
    }

    void check()
    const interval = setInterval(() => void check(), POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  if (count === 0) return null

  return (
    <NavLink to="/watchlist" className="alerts-bell" title={t('alerts.tooltip', { count })}>
      🔔 {count}
    </NavLink>
  )
}
