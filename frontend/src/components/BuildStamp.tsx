import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Health } from '../api/types'
import { useI18n } from '../i18n'

/**
 * Which commit is running, in the footer. The interface and the server are
 * two services restarted separately after a `git pull`; when their commits
 * differ, one of them was forgotten, and the stamp says so.
 */
export function BuildStamp() {
  const { t, formatDate } = useI18n()
  const [build, setBuild] = useState<Health['build'] | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .health()
      .then((health) => {
        if (!cancelled) setBuild(health.build ?? null)
      })
      .catch(() => {
        // The footer is not the place to report an unreachable server.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const frontend = __APP_COMMIT__ || null
  const backend = build?.commit ?? null
  const commit = backend ?? frontend
  if (!commit) return null

  const mismatch = frontend !== null && backend !== null && frontend !== backend
  const title = mismatch
    ? t('build.mismatch', { frontend, backend })
    : build?.committed_at
      ? t('build.committedAt', { date: formatDate(build.committed_at) })
      : undefined

  return (
    <span className={mismatch ? 'build-stamp build-stamp--mismatch' : 'build-stamp'} title={title}>
      {mismatch && <span className="build-stamp__dot" aria-hidden="true" />}
      {t('build.label', { commit })}
      {build?.committed_at && <> · {formatDate(build.committed_at)}</>}
      {mismatch && <span className="visually-hidden"> — {title}</span>}
    </span>
  )
}
