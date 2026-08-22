import { useI18n } from '../i18n'

/** Same visual shape as `ScoreBadge`'s toggle button, but a plain badge —
 * no score band, since this toggles news/commentary, not a score. */
export function InsightsBadge({ expanded, onToggle }: { expanded: boolean; onToggle: () => void }) {
  const { t } = useI18n()

  return (
    <button
      type="button"
      className={`insights-badge ${expanded ? 'insights-badge-expanded' : ''}`}
      title={t('insights.badgeTooltip')}
      onClick={onToggle}
    >
      {t('insights.badgeLabel')}
    </button>
  )
}
