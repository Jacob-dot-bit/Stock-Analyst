import type { Score } from '../api/types'
import { useI18n } from '../i18n'

export function scoreBand(score: number | null): 'high' | 'mid' | 'low' | 'none' {
  if (score === null) return 'none'
  if (score >= 66) return 'high'
  if (score >= 33) return 'mid'
  return 'low'
}

/** Same visual/tooltip shape as `PriceStatusBadge` — a small badge, clicking
 * it expands the per-pillar breakdown row directly underneath. See DEVLOG
 * "Decision 3r.1". */
export function ScoreBadge({
  score,
  expanded,
  onToggle,
}: {
  score: Score | undefined
  expanded: boolean
  onToggle: () => void
}) {
  const { t, formatNumber } = useI18n()
  if (!score || score.composite === null) {
    return <span className="score-badge score-band-none">—</span>
  }

  const scoredPillars = score.pillars.filter((p) => p.score !== null)
  const title = [
    t('scores.compositeTooltip', { score: formatNumber(score.composite, 0) }),
    t('scores.notAdvice'),
    ...scoredPillars.map((p) =>
      t('scores.pillarScoreTooltip', {
        pillar: t(`scores.pillar.${p.name}`),
        score: formatNumber(p.score, 0),
        weight: formatNumber(p.weight_used, 0),
      }),
    ),
    t('scores.clickForDetail'),
  ].join('\n')

  return (
    <button
      type="button"
      className={`score-badge score-band-${scoreBand(score.composite)} ${expanded ? 'score-badge-expanded' : ''}`}
      title={title}
      onClick={onToggle}
    >
      {formatNumber(score.composite, 0)}
      {/* A bare number gives no hint it's clickable — this chevron is the
          visible "there's more here" affordance the tooltip alone can't
          provide (a beginner user never hovers first). */}
      <span className="score-badge-chevron" aria-hidden="true">
        {expanded ? '▴' : '▾'}
      </span>
    </button>
  )
}
