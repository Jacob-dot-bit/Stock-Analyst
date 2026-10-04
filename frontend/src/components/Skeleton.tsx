import { useI18n } from '../i18n'

/** Shimmering placeholder rows standing in for a table or list that is
 * still loading. Keeps roughly the final height so the page doesn't jump
 * when the data arrives; the hidden text tells a screen reader why it is
 * empty. */
export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  const { t } = useI18n()
  return (
    <div className="skeleton-rows" aria-busy="true">
      <span className="visually-hidden">{t('common.loading')}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton skeleton-row" />
      ))}
    </div>
  )
}

/** Placeholder for a whole page section: a row of KPI tiles and a card. */
export function SkeletonCards() {
  return (
    <>
      <div className="stat-grid skeleton-stats" aria-hidden="true">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="skeleton skeleton-stat" />
        ))}
      </div>
      <div className="card">
        <SkeletonRows />
      </div>
    </>
  )
}

/** Shown while a page's code is being fetched (routes load on demand). */
export function SkeletonPage() {
  return (
    <div>
      <div className="page-header" aria-hidden="true">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-subtitle" />
      </div>
      <SkeletonCards />
    </div>
  )
}
