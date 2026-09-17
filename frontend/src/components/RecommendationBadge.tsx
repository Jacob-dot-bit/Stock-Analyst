import { useI18n } from '../i18n'

type Recommendation = 'buy' | 'hold' | 'sell' | null

const CLASS_BY_RECOMMENDATION: Record<'buy' | 'hold' | 'sell', string> = {
  buy: 'resolved',
  hold: 'neutral',
  sell: 'negative',
}

/**
 * An explicit Buy/Hold/Sell verdict, Discovery-only — a deliberate,
 * user-requested exception to this app's usual fact-based labeling
 * (position/watchlist signals elsewhere stay descriptive). See DEVLOG
 * "Decision 3u.21".
 */
export function RecommendationBadge({ recommendation }: { recommendation: Recommendation }) {
  const { t } = useI18n()
  if (recommendation === null) {
    return <span className="tag neutral">{t('discovery.recommendation.none')}</span>
  }
  return (
    <span className={`tag ${CLASS_BY_RECOMMENDATION[recommendation]}`} title={t('discovery.recommendationTooltip')}>
      {t(`discovery.recommendation.${recommendation}`)}
    </span>
  )
}
