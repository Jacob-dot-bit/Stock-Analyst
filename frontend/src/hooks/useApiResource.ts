import { type DependencyList, useCallback, useEffect, useRef, useState } from 'react'

/** The message to show for a failed request. */
export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export interface ApiResource<T> {
  /** null until the first response arrives. */
  data: T | null
  error: string | null
  /** Fetches again, keeping the current data on screen meanwhile. */
  reload: () => void
}

/**
 * Fetch-on-mount for a read-only view: the `data`/`error` pair and the
 * "ignore a response that arrives after unmount or after a newer request"
 * guard that a dozen panels each wrote by hand (DEVLOG "Step 3u.102").
 * Refetches when `deps` change.
 */
export function useApiResource<T>(fetcher: () => Promise<T>, deps: DependencyList): ApiResource<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  useEffect(() => {
    let current = true
    setError(null)
    fetcherRef
      .current()
      .then((result) => {
        if (current) setData(result)
      })
      .catch((err) => {
        if (current) setError(errorMessage(err))
      })
    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the caller's deps decide when to refetch
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, error, reload }
}
