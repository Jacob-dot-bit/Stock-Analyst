import { useEffect, useState } from 'react'

/**
 * Which columns of a table are hidden, persisted per table via `storageKey`.
 * Stores the *hidden* keys, not the visible ones: a column added later
 * defaults to visible for existing users instead of silently disappearing.
 * Same read-once/write-on-change shape as `i18n/index.tsx`'s locale storage.
 */
export function useHiddenColumns(storageKey: string) {
  const [hidden, setHidden] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      return raw ? new Set(JSON.parse(raw)) : new Set()
    } catch {
      return new Set()
    }
  })

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify([...hidden]))
  }, [storageKey, hidden])

  function toggle(key: string) {
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return { hidden, toggle }
}
