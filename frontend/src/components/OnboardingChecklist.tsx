import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { OnboardingStatus } from '../api/types'
import { useI18n } from '../i18n'

const DISMISSED_KEY = 'stock-analyst.onboardingDismissed'

const STEPS: { key: keyof OnboardingStatus; labelKey: string; whyKey: string }[] = [
  { key: 'imported', labelKey: 'onboarding.step.import', whyKey: 'onboarding.why.import' },
  { key: 'prices_refreshed', labelKey: 'onboarding.step.refresh', whyKey: 'onboarding.why.refresh' },
  { key: 'unresolved_resolved', labelKey: 'onboarding.step.unresolved', whyKey: 'onboarding.why.unresolved' },
  { key: 'fundamentals_fetched', labelKey: 'onboarding.step.fundamentals', whyKey: 'onboarding.why.fundamentals' },
  { key: 'allocation_target_set', labelKey: 'onboarding.step.allocation', whyKey: 'onboarding.why.allocation' },
  { key: 'watchlist_started', labelKey: 'onboarding.step.watchlist', whyKey: 'onboarding.why.watchlist' },
]

/**
 * A short "getting started" checklist, shown until every step is done or
 * the user dismisses it — the first-run guidance a brand-new user needs
 * before "what should I check today" (`AttentionCard`) means anything.
 * Each step is a plain existence check the backend already computes
 * (`GET /api/portfolio/onboarding`); this component only renders it and
 * explains, in one line, *why* the step matters. Dismissal is local-only
 * (this is a single-user local app, same `localStorage` convention as
 * `i18n`'s locale and `useHiddenColumns`) — re-completing a step un-hides
 * nothing, but an already-dismissed checklist never reappears either.
 * See DEVLOG "Decision 3u.26".
 */
export function OnboardingChecklist() {
  const { t } = useI18n()
  const [status, setStatus] = useState<OnboardingStatus | null>(null)
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISSED_KEY) === '1')

  useEffect(() => {
    if (dismissed) return
    api.getOnboardingStatus().then(setStatus).catch(() => setStatus(null))
  }, [dismissed])

  function dismiss() {
    localStorage.setItem(DISMISSED_KEY, '1')
    setDismissed(true)
  }

  if (dismissed || status === null) return null
  if (STEPS.every((step) => status[step.key])) return null

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h2>{t('onboarding.title')}</h2>
        <button className="link" onClick={dismiss}>
          {t('onboarding.dismiss')}
        </button>
      </div>
      <ul className="onboarding-list">
        {STEPS.map((step) => {
          const done = status[step.key]
          return (
            <li key={step.key} className={`onboarding-item${done ? ' done' : ''}`}>
              <span className="onboarding-check">{done ? '☑' : '☐'}</span>
              <span>
                <span className="onboarding-label">{t(step.labelKey)}</span>
                {!done && <span className="onboarding-why"> — {t(step.whyKey)}</span>}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
