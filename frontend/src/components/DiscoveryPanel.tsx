import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DiscoveryCandidate } from '../api/types'
import { useI18n } from '../i18n'
import { PredictionBackfillButton } from './PredictionBackfillButton'
import { RecommendationBadge } from './RecommendationBadge'

interface Props {
  onAdded: () => void
  /** Shared with `ScreenerTable` via the parent page (`Screener.tsx`) —
   * one price filter for every "hidden gems" list on the page. Empty
   * string means "no bound". */
  priceMin: string
  priceMax: string
}

type RankBy = 'value' | 'growth'
type FinvizPreset = 'insider_buys' | 'oversold'
type VerdictFilter = 'all' | 'buy' | 'hold' | 'sell'

/**
 * Automated candidate discovery — two sources feeding the same "hidden
 * gems" screener a hand-typed symbol already does, never a new notion of
 * "undervalued" or "high potential": the S&P 500 panel ranks by the app's
 * own existing Value/Growth pillar scores (`GET /api/scoring/scores`
 * already computes these); the Finviz panel surfaces a *different*,
 * narrower signal (insider buying / technical oversold) — deliberately
 * never blended into the Value/Growth ranking. See DEVLOG "Decision 3u.20".
 *
 * Each candidate also carries an explicit Buy/Hold/Sell `recommendation`
 * (mechanically derived from its composite score) — a deliberate,
 * user-requested exception to this app's usual fact-based labeling
 * elsewhere (position/watchlist signals stay descriptive). See DEVLOG
 * "Decision 3u.21".
 */
export function DiscoveryPanel({ onAdded, priceMin, priceMax }: Props) {
  const { t, formatNumber } = useI18n()
  const [rankBy, setRankBy] = useState<RankBy>('value')
  const [candidates, setCandidates] = useState<DiscoveryCandidate[] | null>(null)
  const [importNotice, setImportNotice] = useState<string | null>(null)
  const [refreshNotice, setRefreshNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [finvizResults, setFinvizResults] = useState<Partial<Record<FinvizPreset, DiscoveryCandidate[]>>>({})
  const [finvizFailed, setFinvizFailed] = useState<Partial<Record<FinvizPreset, number>>>({})
  const [finvizBusy, setFinvizBusy] = useState<FinvizPreset | null>(null)
  // Applies to both lists below (S&P 500 ranking and Finviz scans) — the
  // hand-picked `ScreenerTable` candidates carry no `recommendation` field,
  // so this filter has nothing to do with them and stays local to this
  // panel rather than lifted to `Screener.tsx` like the price filter is.
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>('all')

  async function loadCandidates(nextRankBy: RankBy) {
    setError(null)
    try {
      setCandidates(await api.getDiscoveryCandidates(nextRankBy))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  useEffect(() => {
    void loadCandidates(rankBy)
  }, [rankBy])

  async function handleImport() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.importSp500Universe()
      setImportNotice(
        t('discovery.importResult', { imported: result.imported, alreadyPresent: result.already_present }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function handleRefresh() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.refreshDiscovery()
      setRefreshNotice(
        result.remaining > 0
          ? t('discovery.refreshResultMore', { evaluated: result.evaluated, remaining: result.remaining })
          : t('discovery.refreshResultDone', { evaluated: result.evaluated }),
      )
      await loadCandidates(rankBy)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function handleRankByChange(nextRankBy: RankBy) {
    setRankBy(nextRankBy)
  }

  function removeEverywhere(instrumentId: number) {
    setCandidates((prev) => prev && prev.filter((c) => c.instrument.id !== instrumentId))
    setFinvizResults((prev) => {
      const next: Partial<Record<FinvizPreset, DiscoveryCandidate[]>> = {}
      for (const key of Object.keys(prev) as FinvizPreset[]) {
        next[key] = prev[key]?.filter((c) => c.instrument.id !== instrumentId)
      }
      return next
    })
  }

  async function handleAdd(candidate: DiscoveryCandidate) {
    setError(null)
    try {
      await api.addScreenerCandidate({
        broker_symbol: candidate.instrument.broker_symbol,
        company_name: candidate.instrument.name,
      })
      removeEverywhere(candidate.instrument.id)
      onAdded()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleFinviz(preset: FinvizPreset) {
    setFinvizBusy(preset)
    setError(null)
    try {
      const result = await api.scanFinvizPreset(preset)
      setFinvizResults((prev) => ({ ...prev, [preset]: result.candidates }))
      setFinvizFailed((prev) => ({ ...prev, [preset]: result.failed }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setFinvizBusy(null)
    }
  }

  // Empty string parses to NaN, not 0 — comparisons against NaN are always
  // false, so an empty bound must map to `null` (no bound) explicitly.
  const minPrice = priceMin.trim() === '' ? null : Number(priceMin)
  const maxPrice = priceMax.trim() === '' ? null : Number(priceMax)

  function withinPriceRange(c: DiscoveryCandidate): boolean {
    if (minPrice === null && maxPrice === null) return true
    // A candidate with no known price can't be confirmed to be within a
    // price filter's range — excluded rather than shown as a false match.
    if (c.current_price === null) return false
    if (minPrice !== null && c.current_price < minPrice) return false
    if (maxPrice !== null && c.current_price > maxPrice) return false
    return true
  }

  function matchesVerdictFilter(c: DiscoveryCandidate): boolean {
    if (verdictFilter === 'all') return true
    // Same convention as the price filter: a candidate with no
    // computable verdict is excluded when a specific one is asked for,
    // never shown as if it matched.
    return c.recommendation === verdictFilter
  }

  function candidateRow(c: DiscoveryCandidate, showScores: boolean) {
    return (
      <tr key={c.instrument.id}>
        <td>
          <strong>{c.instrument.broker_symbol}</strong>
          {c.instrument.name && (
            <div className="muted" style={{ fontSize: '0.78rem' }}>
              {c.instrument.name}
            </div>
          )}
        </td>
        <td className="num">{c.current_price !== null ? formatNumber(c.current_price) : '—'}</td>
        {showScores && (
          <>
            <td className="num">{c.value_score !== null ? formatNumber(c.value_score, 0) : '—'}</td>
            <td className="num">{c.growth_score !== null ? formatNumber(c.growth_score, 0) : '—'}</td>
          </>
        )}
        <td>
          <RecommendationBadge recommendation={c.recommendation} />
        </td>
        <td>
          <button className="link" onClick={() => void handleAdd(c)}>
            {t('common.add')}
          </button>
        </td>
      </tr>
    )
  }

  return (
    <div className="card">
      <h2>{t('discovery.title')}</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {t('discovery.description')}
      </p>

      {error && <div className="notice error">{error}</div>}

      <div style={{ marginBottom: '1.2rem' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.verdictFilterLabel')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.verdictFilterHint')}
        </p>
        <div className="form-row">
          {(['all', 'buy', 'hold', 'sell'] as VerdictFilter[]).map((option) => (
            <button
              key={option}
              className={verdictFilter === option ? 'primary' : undefined}
              onClick={() => setVerdictFilter(option)}
            >
              {option === 'all' ? t('filters.all') : t(`discovery.recommendation.${option}`)}
            </button>
          ))}
        </div>
      </div>

      <div style={{ marginBottom: '1.2rem' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.sp500.title')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.sp500.description')}
        </p>
        <div className="form-row">
          <button onClick={() => void handleImport()} disabled={busy}>
            {t('discovery.sp500.import')}
          </button>
          <button onClick={() => void handleRefresh()} disabled={busy}>
            {busy ? t('common.saving') : t('discovery.sp500.refresh')}
          </button>
          <button className={rankBy === 'value' ? 'primary' : undefined} onClick={() => void handleRankByChange('value')}>
            {t('discovery.rankByValue')}
          </button>
          <button className={rankBy === 'growth' ? 'primary' : undefined} onClick={() => void handleRankByChange('growth')}>
            {t('discovery.rankByGrowth')}
          </button>
        </div>
        {importNotice && (
          <div className="muted" style={{ fontSize: '0.82rem', marginTop: '0.4rem' }}>
            {importNotice}
          </div>
        )}
        {refreshNotice && (
          <div className="muted" style={{ fontSize: '0.82rem' }}>
            {refreshNotice}
          </div>
        )}

        {candidates && candidates.length === 0 && <div className="empty">{t('discovery.empty')}</div>}
        {candidates && candidates.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('table.instrument')}</th>
                  <th className="num">{t('table.price')}</th>
                  <th className="num">{t('discovery.valueScore')}</th>
                  <th className="num">{t('discovery.growthScore')}</th>
                  <th>{t('discovery.recommendationColumn')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {candidates
                  .filter(withinPriceRange)
                  .filter(matchesVerdictFilter)
                  .map((c) => candidateRow(c, true))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.finviz.title')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.finviz.description')}
        </p>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.78rem' }}>
          {t('discovery.finviz.slowNotice')}
        </p>
        <div className="form-row">
          <button onClick={() => void handleFinviz('insider_buys')} disabled={finvizBusy !== null}>
            {finvizBusy === 'insider_buys' ? t('common.saving') : t('discovery.finviz.insiderBuys')}
          </button>
          <button onClick={() => void handleFinviz('oversold')} disabled={finvizBusy !== null}>
            {finvizBusy === 'oversold' ? t('common.saving') : t('discovery.finviz.oversold')}
          </button>
        </div>

        {finvizBusy !== null && (
          <div className="refresh-progress" style={{ marginTop: '0.6rem' }}>
            <div className="refresh-progress-track">
              <div className="refresh-progress-fill indeterminate" />
            </div>
            <div className="refresh-progress-label muted">{t('discovery.finviz.scanningNotice')}</div>
          </div>
        )}

        {(['insider_buys', 'oversold'] as FinvizPreset[]).map((preset) => {
          const results = finvizResults[preset]
          if (!results) return null
          const failedCount = finvizFailed[preset] ?? 0
          const filteredResults = results.filter(withinPriceRange).filter(matchesVerdictFilter)
          return (
            <div key={preset} style={{ marginTop: '0.6rem' }}>
              <div className="muted" style={{ fontSize: '0.82rem' }}>
                {t(`discovery.finviz.${preset === 'insider_buys' ? 'insiderBuys' : 'oversold'}`)}
              </div>
              {failedCount > 0 && (
                <div className="muted" style={{ fontSize: '0.78rem' }}>
                  {t('discovery.finviz.failedCount', { count: failedCount })}
                </div>
              )}
              {filteredResults.length === 0 ? (
                <div className="empty">{t('discovery.empty')}</div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>{t('table.instrument')}</th>
                        <th className="num">{t('table.price')}</th>
                        <th>{t('discovery.recommendationColumn')}</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>{filteredResults.map((c) => candidateRow(c, false))}</tbody>
                  </table>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div style={{ marginTop: '1.2rem' }}>
        <PredictionBackfillButton />
      </div>
    </div>
  )
}
