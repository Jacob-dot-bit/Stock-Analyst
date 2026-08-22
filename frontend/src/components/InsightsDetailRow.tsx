import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { InstrumentCommentary, NewsSentiment } from '../api/types'
import { useI18n } from '../i18n'

type Loadable<T> = T | 'loading' | null

/** Alpha Vantage's raw label ("Bullish", "Somewhat-Bullish", "Neutral",
 * "Somewhat-Bearish", "Bearish") normalized to one of this app's own i18n
 * keys — never shown untranslated, and never colored green/red: it
 * describes an article's tone, not the app's own view of the instrument.
 * See DEVLOG "Decision 3u.38". */
const SENTIMENT_KEY: Record<string, string> = {
  bullish: 'insights.sentiment.bullish',
  'somewhat-bullish': 'insights.sentiment.somewhatBullish',
  neutral: 'insights.sentiment.neutral',
  'somewhat-bearish': 'insights.sentiment.somewhatBearish',
  bearish: 'insights.sentiment.bearish',
}

function sentimentLabel(rawLabel: string, t: (key: string) => string): string {
  const normalized = rawLabel.toLowerCase().replace(/\s+/g, '-')
  const key = SENTIMENT_KEY[normalized]
  return key ? t(key) : t('insights.sentiment.unknown')
}

/** The full news/sentiment + AI-commentary panel for one instrument —
 * extracted so both the standalone table row below (Watchlist/Screener) and
 * the consolidated per-position detail panel (`PositionDetailRow.tsx`) can
 * render the exact same content without duplicating the fetch logic. See
 * DEVLOG "Decision 3u.31".
 *
 * Two sections with asymmetric weight matching their real cost (DEVLOG
 * "Decision 0.3"): news is free and fetches automatically the moment this
 * mounts (mounting it already *is* the one-instrument-at-a-time explicit
 * action); AI commentary is paid, so it waits for its own, separate, more
 * deliberate click.
 */
export function InsightsSection({ instrumentId }: { instrumentId: number }) {
  const { t, formatDate } = useI18n()
  const [news, setNews] = useState<Loadable<NewsSentiment>>('loading')
  const [commentary, setCommentary] = useState<Loadable<InstrumentCommentary>>(null)
  // React 18 StrictMode intentionally double-invokes this effect in
  // development (mount, cleanup, mount again) to surface missing cleanup —
  // harmless for the read-only GETs elsewhere in this app, but this effect
  // fires a real POST that spends a live Alpha Vantage request and writes to
  // the DB. A ref survives that synchronous double-invoke (same component
  // instance) and only ever changes when `instrumentId` genuinely changes,
  // so it doubles as the "is this response still relevant" check: a plain
  // per-invocation `cancelled` boolean would get set by StrictMode's
  // cleanup between the two invocations and then silently swallow the one
  // real fetch's result when it resolves — this ref doesn't, since nothing
  // resets it back except a real instrumentId change.
  const fetchedForRef = useRef<number | null>(null)

  useEffect(() => {
    if (fetchedForRef.current === instrumentId) return
    fetchedForRef.current = instrumentId

    setNews('loading')
    api
      .getInstrumentNews(instrumentId)
      .then((result) => {
        if (fetchedForRef.current === instrumentId) setNews(result)
      })
      .catch(() => {
        if (fetchedForRef.current === instrumentId) setNews(null)
      })
  }, [instrumentId])

  function handleAskPerplexity() {
    setCommentary('loading')
    api
      .getInstrumentCommentary(instrumentId)
      .then(setCommentary)
      .catch(() => setCommentary(null))
  }

  return (
        <div className="insights-detail">
          <section className="insights-section">
            <h4>{t('insights.newsTitle')}</h4>
            {news === 'loading' && <p className="muted">{t('common.loading')}</p>}
            {news === null && <p className="muted">{t('insights.noNews')}</p>}
            {news && news !== 'loading' && news.articles.length === 0 && (
              <p className="muted">
                {news.outcome.code === 'news.empty'
                  ? t('insights.noNews')
                  : t(news.outcome.code, news.outcome.params)}
              </p>
            )}
            {news && news !== 'loading' && news.articles.length > 0 && (
              <ul className="insights-articles">
                {news.articles.map((article) => (
                  <li key={article.url} className="insights-article">
                    <a href={article.url} target="_blank" rel="noopener noreferrer">
                      {article.title}
                    </a>
                    <span className="muted">
                      {' — '}
                      {article.source}, {formatDate(article.time_published)}
                    </span>
                    <span className="sentiment-tag" title={t('insights.sentimentTooltip')}>
                      {sentimentLabel(article.ticker_sentiment_label, t)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="insights-section">
            <h4>{t('insights.commentaryTitle')}</h4>
            {commentary === null && (
              <button type="button" onClick={handleAskPerplexity}>
                {t('insights.askPerplexity')}
              </button>
            )}
            {commentary === 'loading' && <p className="muted">{t('common.loading')}</p>}
            {commentary && commentary !== 'loading' && (
              <>
                {commentary.content ? (
                  <>
                    <p className="muted" style={{ fontSize: '0.85rem' }}>
                      {t('insights.commentaryDisclaimer')}
                    </p>
                    <p>{commentary.content}</p>
                    {commentary.citations.length > 0 && (
                      <ul className="insights-citations">
                        {commentary.citations.map((citation) => (
                          <li key={citation.url}>
                            <a href={citation.url} target="_blank" rel="noopener noreferrer">
                              {citation.title ?? citation.url}
                            </a>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                ) : (
                  <p className="muted">{t(commentary.outcome.code, commentary.outcome.params)}</p>
                )}
              </>
            )}
          </section>
        </div>
  )
}

/** Standalone table row wrapping `InsightsSection` — no modal/portal exists
 * in this codebase to reuse, so this stays a plain extra `<tr>` like the
 * rest of the table. Used by Watchlist/Screener; `PositionsTable` embeds
 * `InsightsSection` directly inside its consolidated detail panel instead. */
export function InsightsDetailRow({ instrumentId, colSpan }: { instrumentId: number; colSpan: number }) {
  return (
    <tr className="insights-detail-row">
      <td colSpan={colSpan}>
        <InsightsSection instrumentId={instrumentId} />
      </td>
    </tr>
  )
}
