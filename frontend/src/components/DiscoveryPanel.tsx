import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DiscoveryCandidate } from '../api/types'
import { useI18n } from '../i18n'
import { BacktestPanel } from './BacktestPanel'
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
  const { t, formatNumber, formatCompactNumber } = useI18n()
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
  // The "simplest cut" data-quality gate: a computed score, a fresh and
  // correctly mapped price, and no unresolved corporate-action candidate.
  // See DEVLOG "Step 3u.62"'s addendum.
  const [dataQualityOnly, setDataQualityOnly] = useState(false)
  // `country`/`sector` also exist on `ScreenerCandidate.instrument`, so
  // these two *could* be lifted to `Screener.tsx` like the price filter —
  // kept local for now (same scope as verdict/data quality) since their
  // option lists are derived from Discovery's own data, not Candidates'.
  // See DEVLOG "Decision 3u.64".
  const [marketFilter, setMarketFilter] = useState('all')
  const [sectorFilter, setSectorFilter] = useState('all')
  // Same local-to-this-panel scope as verdict/data-quality/market/sector —
  // `market_cap`/`debt_ratio`/`price_history_years` only exist on
  // `DiscoveryCandidate`, not `ScreenerCandidate`. See DEVLOG
  // "Decision 3u.72".
  const [capMin, setCapMin] = useState('')
  const [capMax, setCapMax] = useState('')
  const [debtMax, setDebtMax] = useState('')
  const [historyMin, setHistoryMin] = useState('')
  // Same local scope as the other three — `dividend_yield_estimate` also
  // only exists on `DiscoveryCandidate`. See DEVLOG "Decision 3u.73".
  const [dividendMin, setDividendMin] = useState('')
  const [dividendBackfillNotice, setDividendBackfillNotice] = useState<string | null>(null)
  const [dividendBackfillBusy, setDividendBackfillBusy] = useState(false)
  // `composite_score` already exists (Decision 3u.20) — this is a plain
  // threshold on it, no new field needed. See DEVLOG "Decision 3u.75".
  const [scoreMin, setScoreMin] = useState('')

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

  function matchesDataQualityFilter(c: DiscoveryCandidate): boolean {
    if (!dataQualityOnly) return true
    return c.composite_score !== null && c.instrument.price_status === 'fresh' && !c.corporate_action_pending
  }

  function matchesMarketFilter(c: DiscoveryCandidate): boolean {
    if (marketFilter === 'all') return true
    // Same "unknown excluded, never a false match" convention as every
    // other filter here: no country on record can't be confirmed to
    // match a specific one asked for.
    return c.instrument.country === marketFilter
  }

  function matchesSectorFilter(c: DiscoveryCandidate): boolean {
    if (sectorFilter === 'all') return true
    return c.instrument.sector === sectorFilter
  }

  const minCap = capMin.trim() === '' ? null : Number(capMin)
  const maxCap = capMax.trim() === '' ? null : Number(capMax)

  function withinCapRange(c: DiscoveryCandidate): boolean {
    if (minCap === null && maxCap === null) return true
    // Same "unknown excluded, never a false match" convention as the
    // price filter: a candidate with no computable market cap can't be
    // confirmed to be within a range that was actually asked for.
    if (c.market_cap === null) return false
    if (minCap !== null && c.market_cap < minCap) return false
    if (maxCap !== null && c.market_cap > maxCap) return false
    return true
  }

  const maxDebt = debtMax.trim() === '' ? null : Number(debtMax)

  function withinDebtLimit(c: DiscoveryCandidate): boolean {
    if (maxDebt === null) return true
    if (c.debt_ratio === null) return false
    return c.debt_ratio <= maxDebt
  }

  const minHistory = historyMin.trim() === '' ? null : Number(historyMin)

  function withinHistoryMin(c: DiscoveryCandidate): boolean {
    if (minHistory === null) return true
    if (c.price_history_years === null) return false
    return c.price_history_years >= minHistory
  }

  // The field takes a percentage (e.g. "2" for 2%); the stored value is a
  // fraction, same convention as `dividend_yield_estimate` itself.
  const minDividend = dividendMin.trim() === '' ? null : Number(dividendMin) / 100

  function withinDividendMin(c: DiscoveryCandidate): boolean {
    if (minDividend === null) return true
    if (c.dividend_yield_estimate === null) return false
    return c.dividend_yield_estimate >= minDividend
  }

  const minScore = scoreMin.trim() === '' ? null : Number(scoreMin)

  function withinScoreMin(c: DiscoveryCandidate): boolean {
    if (minScore === null) return true
    // A candidate with no composite score at all has nothing to compare
    // against a threshold — same "unknown excluded" rule as every other
    // filter here, not shown as if it cleared the bar.
    if (c.composite_score === null) return false
    return c.composite_score >= minScore
  }

  async function handleDividendBackfill() {
    setDividendBackfillBusy(true)
    setError(null)
    try {
      const result = await api.backfillDiscoveryDividends()
      setDividendBackfillNotice(
        result.remaining > 0
          ? t('discovery.refreshResultMore', { evaluated: result.evaluated, remaining: result.remaining })
          : t('discovery.refreshResultDone', { evaluated: result.evaluated }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDividendBackfillBusy(false)
    }
  }

  // Option lists reflect what's actually loaded right now (S&P 500 +
  // Finviz combined) rather than a fixed taxonomy — a filter never offers
  // a choice that would just show an empty list.
  const allLoadedCandidates = [...(candidates ?? []), ...Object.values(finvizResults).flatMap((v) => v ?? [])]
  const availableMarkets = [...new Set(allLoadedCandidates.map((c) => c.instrument.country).filter((v): v is string => v !== null))].sort()
  const availableSectors = [...new Set(allLoadedCandidates.map((c) => c.instrument.sector).filter((v): v is string => v !== null))].sort()

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
            <td className="num">{c.market_cap !== null ? formatCompactNumber(c.market_cap) : '—'}</td>
            <td className="num">{c.debt_ratio !== null ? formatNumber(c.debt_ratio) : '—'}</td>
            <td className="num">
              {c.dividend_yield_estimate !== null ? `${formatNumber(c.dividend_yield_estimate * 100)}%` : '—'}
            </td>
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
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.dataQualityFilterLabel')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.dataQualityFilterHint')}
        </p>
        <label>
          <input
            type="checkbox"
            checked={dataQualityOnly}
            onChange={(e) => setDataQualityOnly(e.target.checked)}
          />{' '}
          {t('discovery.dataQualityFilterOption')}
        </label>
      </div>

      <div style={{ marginBottom: '1.2rem' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.marketSectorFilterLabel')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.marketSectorFilterHint')}
        </p>
        <div className="form-row">
          <div className="field">
            <label htmlFor="discovery-market-filter">{t('breakdown.dimension.country')}</label>
            <select id="discovery-market-filter" value={marketFilter} onChange={(e) => setMarketFilter(e.target.value)}>
              <option value="all">{t('filters.all')}</option>
              {availableMarkets.map((market) => (
                <option key={market} value={market}>
                  {market}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="discovery-sector-filter">{t('breakdown.dimension.sector')}</label>
            <select id="discovery-sector-filter" value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)}>
              <option value="all">{t('filters.all')}</option>
              {availableSectors.map((sector) => (
                <option key={sector} value={sector}>
                  {sector}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div style={{ marginBottom: '1.2rem' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.marketCapFilterLabel')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.marketCapFilterHint')}
        </p>
        <div className="form-row">
          <div className="field">
            <label htmlFor="discovery-cap-min">{t('filters.capMin')}</label>
            <input id="discovery-cap-min" value={capMin} onChange={(e) => setCapMin(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="discovery-cap-max">{t('filters.capMax')}</label>
            <input id="discovery-cap-max" value={capMax} onChange={(e) => setCapMax(e.target.value)} />
          </div>
        </div>
      </div>

      <div style={{ marginBottom: '1.2rem' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.debtRatioFilterLabel')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.debtRatioFilterHint')}
        </p>
        <div className="field">
          <label htmlFor="discovery-debt-max">{t('filters.debtMax')}</label>
          <input id="discovery-debt-max" value={debtMax} onChange={(e) => setDebtMax(e.target.value)} />
        </div>
      </div>

      <div style={{ marginBottom: '1.2rem' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.historyFilterLabel')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.historyFilterHint')}
        </p>
        <div className="field">
          <label htmlFor="discovery-history-min">{t('filters.historyMin')}</label>
          <input id="discovery-history-min" value={historyMin} onChange={(e) => setHistoryMin(e.target.value)} />
        </div>
      </div>

      <div style={{ marginBottom: '1.2rem' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.dividendFilterLabel')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.dividendFilterHint')}
        </p>
        <div className="field">
          <label htmlFor="discovery-dividend-min">{t('filters.dividendMin')}</label>
          <input id="discovery-dividend-min" value={dividendMin} onChange={(e) => setDividendMin(e.target.value)} />
        </div>
      </div>

      <div style={{ marginBottom: '1.2rem' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('discovery.scoreFilterLabel')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('discovery.scoreFilterHint')}
        </p>
        <div className="field">
          <label htmlFor="discovery-score-min">{t('filters.scoreMin')}</label>
          <input id="discovery-score-min" value={scoreMin} onChange={(e) => setScoreMin(e.target.value)} />
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
          <button onClick={() => void handleDividendBackfill()} disabled={dividendBackfillBusy}>
            {dividendBackfillBusy ? t('common.saving') : t('discovery.backfillDividends')}
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
        {dividendBackfillNotice && (
          <div className="muted" style={{ fontSize: '0.82rem' }}>
            {dividendBackfillNotice}
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
                  <th className="num" title={t('discovery.valueScoreTooltip')}>
                    {t('discovery.valueScore')}
                  </th>
                  <th className="num" title={t('discovery.growthScoreTooltip')}>
                    {t('discovery.growthScore')}
                  </th>
                  <th className="num">{t('discovery.marketCap')}</th>
                  <th className="num">{t('discovery.debtRatio')}</th>
                  <th className="num">{t('discovery.dividendYield')}</th>
                  <th>{t('discovery.recommendationColumn')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {candidates
                  .filter(withinPriceRange)
                  .filter(matchesVerdictFilter)
                  .filter(matchesDataQualityFilter)
                  .filter(matchesMarketFilter)
                  .filter(matchesSectorFilter)
                  .filter(withinCapRange)
                  .filter(withinDebtLimit)
                  .filter(withinHistoryMin)
                  .filter(withinDividendMin)
                  .filter(withinScoreMin)
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
          const filteredResults = results
            .filter(withinPriceRange)
            .filter(matchesVerdictFilter)
            .filter(matchesDataQualityFilter)
            .filter(matchesMarketFilter)
            .filter(matchesSectorFilter)
            .filter(withinCapRange)
            .filter(withinDebtLimit)
            .filter(withinHistoryMin)
            .filter(withinDividendMin)
            .filter(withinScoreMin)
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

      <div style={{ marginTop: '1.2rem' }}>
        <BacktestPanel />
      </div>
    </div>
  )
}
