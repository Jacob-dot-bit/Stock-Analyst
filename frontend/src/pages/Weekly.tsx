import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { AttentionItem, WeeklySummary } from '../api/types'
import { rangeLabel } from '../format'
import { useI18n } from '../i18n'
import { SkeletonCards } from '../components/Skeleton'

function Section({ title, link, linkLabel, children }: { title: string; link: string; linkLabel: string; children: ReactNode }) {
  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '1rem' }}>
        <h2>{title}</h2>
        <Link to={link}>{linkLabel}</Link>
      </div>
      {children}
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return (
    <p className="muted section-desc">
      {text}
    </p>
  )
}

/**
 * "What to look at this week" — one read gathering facts the app already
 * shows on separate pages: personal policy gaps, allocation gaps, positions
 * where score and allocation line up, watchlist targets, journal reviews,
 * and the data freshness every one of those depends on. Descriptive only,
 * like the rest of the app: nothing here is phrased as a trade. See DEVLOG
 * "Decision 3u.80".
 */
export function Weekly() {
  const { t, formatNumber, formatSignedPercent, formatDate } = useI18n()
  const [summary, setSummary] = useState<WeeklySummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getWeeklySummary()
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const categoryLabel = (category: string | null) => {
    if (!category || category === 'UNKNOWN') return t('breakdown.unknown')
    const key = `breakdown.category.${category}`
    const translated = t(key)
    return translated === key ? category : translated
  }

  const dataItemText = (item: AttentionItem) => {
    switch (item.kind) {
      case 'unresolved_instruments':
        return t('attention.unresolvedInstruments', { count: item.count })
      case 'price_error':
        return t('attention.priceError', { count: item.count })
      default:
        return t('attention.priceStale', { count: item.count })
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>{t('weekly.title')}</h1>
        <p>{summary ? t('weekly.subtitle', { date: formatDate(summary.as_of) }) : t('weekly.subtitleLoading')}</p>
      </div>

      <div className="notice info">{t('weekly.disclaimer')}</div>

      {error && <div className="notice error">{error}</div>}

      {!summary && !error && <SkeletonCards />}

      {summary && (
        <>
          <Section title={t('weekly.policy.title')} link="/portfolio" linkLabel={t('weekly.openPortfolio')}>
            {summary.policy_gaps.length === 0 ? (
              <Empty text={t('weekly.policy.empty')} />
            ) : (
              <ul className="attention-list">
                {summary.policy_gaps.map((gap, i) => (
                  <li key={`${gap.limit_id}-${gap.target ?? ''}-${i}`} className="attention-item warning">
                    {t(`policy.dimension.${gap.dimension}`)}
                    {gap.target ? ` — ${gap.target}` : ''}
                    {': '}
                    {formatNumber(gap.current_pct, 1)}%{' '}
                    <span className="tag unresolved">{t(`allocation.state.${gap.state}`)}</span>{' '}
                    {t('policy.gaps.yourLimit', { range: rangeLabel(gap.min_pct, gap.max_pct, (v) => formatNumber(v, 1)) })}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title={t('weekly.allocation.title')} link="/portfolio" linkLabel={t('weekly.openPortfolio')}>
            {summary.allocation_gaps.length === 0 ? (
              <Empty text={t('weekly.allocation.empty')} />
            ) : (
              <ul className="attention-list">
                {summary.allocation_gaps.map((row) => (
                  <li key={row.category} className="attention-item warning">
                    {categoryLabel(row.category)}: {formatNumber(row.current_pct, 1)}%{' '}
                    <span className="tag unresolved">{t(`allocation.state.${row.state}`)}</span>{' '}
                    {t('weekly.allocation.detail', {
                      range: rangeLabel(row.min_pct, row.max_pct, (v) => formatNumber(v, 1)),
                      gap: formatNumber(row.gap_pct, 1),
                    })}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title={t('weekly.positions.title')} link="/portfolio" linkLabel={t('weekly.openPortfolio')}>
            {summary.position_flags.length === 0 ? (
              <Empty text={t('weekly.positions.empty')} />
            ) : (
              <>
                <p className="muted section-desc">
                  {t('weekly.positions.note')}
                </p>
                <ul className="attention-list">
                  {summary.position_flags.map((flag) => (
                    <li key={flag.instrument_id} className="attention-item warning">
                      <strong>{flag.symbol}</strong>
                      {flag.name ? ` (${flag.name})` : ''}{' '}
                      <span className="tag unresolved">
                        {t(flag.signal === 'reinforce' ? 'signals.positionReinforceFact' : 'signals.positionReduceFact')}
                      </span>{' '}
                      {t('weekly.positions.detail', {
                        weight: formatNumber(flag.weight_percent, 1),
                        score: formatNumber(flag.composite_score, 0),
                        category: categoryLabel(flag.category),
                        state: t(`allocation.state.${flag.allocation_state}`).toLowerCase(),
                        gap: formatNumber(flag.gap_pct, 1),
                      })}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Section>

          <Section title={t('weekly.watchlist.title')} link="/watchlist" linkLabel={t('weekly.openWatchlist')}>
            {summary.watchlist_flags.length === 0 ? (
              <Empty text={t('weekly.watchlist.empty')} />
            ) : (
              <ul className="attention-list">
                {summary.watchlist_flags.map((flag) => (
                  <li key={flag.instrument_id} className="attention-item warning">
                    <strong>{flag.symbol}</strong>
                    {flag.name ? ` (${flag.name})` : ''}{' '}
                    <span className="tag unresolved">{t(`weekly.watchlist.kind.${flag.kind}`)}</span>{' '}
                    {t('weekly.watchlist.detail', {
                      distance: formatSignedPercent(flag.distance_to_target_pct),
                      target: formatNumber(flag.target_entry_price),
                    })}
                    {flag.composite_score !== null && t('weekly.scoreSuffix', { score: formatNumber(flag.composite_score, 0) })}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title={t('weekly.journal.title')} link="/journal" linkLabel={t('weekly.openJournal')}>
            {summary.journal_due.length === 0 ? (
              <Empty text={t('weekly.journal.empty', { date: formatDate(summary.window_end) })} />
            ) : (
              <ul className="attention-list">
                {summary.journal_due.map((entry) => (
                  <li key={entry.id} className="attention-item warning">
                    <span className={`tag ${entry.overdue ? 'confidence-review' : 'neutral'}`}>
                      {t(entry.overdue ? 'weekly.journal.overdue' : 'weekly.journal.due', {
                        date: formatDate(entry.review_date),
                      })}
                    </span>
                    {entry.symbol && <strong>{entry.symbol}</strong>}
                    <span>{entry.thesis.length > 140 ? `${entry.thesis.slice(0, 140)}…` : entry.thesis}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section
            title={t('weekly.data.title')}
            link="/settings#integrite-corrections"
            linkLabel={t('weekly.openSettings')}
          >
            {summary.data_reliability.length === 0 ? (
              <Empty text={t('weekly.data.empty')} />
            ) : (
              <>
                <p className="muted section-desc">
                  {t('weekly.data.note')}
                </p>
                <ul className="attention-list">
                  {summary.data_reliability.map((item) => (
                    <li key={item.kind} className={`attention-item ${item.severity}`}>
                      {dataItemText(item)}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Section>
        </>
      )}
    </>
  )
}
