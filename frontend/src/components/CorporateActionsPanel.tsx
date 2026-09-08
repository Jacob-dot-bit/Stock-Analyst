import { Fragment, useEffect, useState } from 'react'
import { api } from '../api/client'
import type {
  CorporateAction,
  CorporateActionCoverage,
  CorporateActionDetection,
  CorporateActionResumeStatus,
  DetectOneResult,
  Instrument,
  OutstandingCandidate,
} from '../api/types'
import { useI18n } from '../i18n'

//: Failure shapes for the targeted single-instrument check — never
//: rendered as "no split", same discipline as the bulk scan's `failed`.
const DETECT_ONE_FAILURE_STATUSES = new Set(['not_supported', 'plan_limited', 'rate_limited', 'failed'])

//: Which CSS badge class each confidence maps to — blue/"confirmed" for
//: the two auto-applied states, amber/"review" for everything still
//: outstanding, neutral for a hand-entered or manually-confirmed row.
//: Never red: none of these mean something is broken. See DEVLOG "Step 3u.57".
const CONFIDENCE_BADGE_CLASS: Record<string, string> = {
  verified_three_sources: 'confidence-confirmed',
  verified_cross_source: 'confidence-confirmed',
  candidate_single_source: 'confidence-review',
  provider_conflict: 'confidence-review',
  suspect_ticker_reuse: 'confidence-review',
  manual_promotion: 'confidence-neutral',
  manual: 'confidence-neutral',
}

function ConfidenceBadge({ confidence }: { confidence: string }) {
  const { t } = useI18n()
  const cls = CONFIDENCE_BADGE_CLASS[confidence] ?? 'confidence-neutral'
  return <span className={`tag ${cls}`}>{t(`corporateActions.confidence.${confidence}`)}</span>
}

/**
 * Stock splits/reverse splits: manual entry, an automatic cross-source
 * detector (Alpha Vantage + Polygon, joined conditionally by FMP), and a
 * targeted on-demand EODHD check. See DEVLOG "Decision 3u.30"/"Decision
 * 3u.41"/"Step 3u.57" (Phase 4 frontend).
 *
 * Instruments and events are always counted and labeled separately — one
 * instrument (e.g. BIVI.US) can carry several corporate-action events.
 * Never present a count of one as if it were the other.
 */
export function CorporateActionsPanel() {
  const { t, formatDate } = useI18n()
  const [actions, setActions] = useState<CorporateAction[] | null>(null)
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [error, setError] = useState<string | null>(null)
  const [detection, setDetection] = useState<CorporateActionDetection | null>(null)
  const [detecting, setDetecting] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [instrumentId, setInstrumentId] = useState('')
  const [actionType, setActionType] = useState<'split' | 'reverse_split'>('split')
  const [effectiveDate, setEffectiveDate] = useState('')
  const [ratioNumerator, setRatioNumerator] = useState('')
  const [ratioDenominator, setRatioDenominator] = useState('')
  const [checkInstrumentId, setCheckInstrumentId] = useState('')
  const [checkingOne, setCheckingOne] = useState(false)
  const [oneResult, setOneResult] = useState<DetectOneResult | null>(null)
  const [oneError, setOneError] = useState<string | null>(null)
  const [coverage, setCoverage] = useState<CorporateActionCoverage | null>(null)
  const [resumeStatus, setResumeStatus] = useState<CorporateActionResumeStatus | null>(null)
  const [resuming, setResuming] = useState(false)
  const [resumeError, setResumeError] = useState<string | null>(null)
  const [outstanding, setOutstanding] = useState<OutstandingCandidate[] | null>(null)
  const [expandedActionId, setExpandedActionId] = useState<number | null>(null)

  function load() {
    setError(null)
    api
      .getCorporateActions()
      .then(setActions)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  function loadCoverage() {
    api.getCorporateActionsCoverage().then(setCoverage).catch(() => setCoverage(null))
    api.getCorporateActionsResumeStatus().then(setResumeStatus).catch(() => setResumeStatus(null))
    api.getOutstandingCorporateActionCandidates().then(setOutstanding).catch(() => setOutstanding(null))
  }

  useEffect(load, [])
  useEffect(loadCoverage, [])

  useEffect(() => {
    // Tracked instruments this app already knows about — the only ones a
    // split can meaningfully be recorded against — merged from the three
    // places an instrument can come from, deduplicated by id.
    Promise.all([api.getPortfolio(), api.getWatchlist(), api.getScreenerCandidates()])
      .then(([portfolio, watchlist, screener]) => {
        const byId = new Map<number, Instrument>()
        for (const position of portfolio.positions) byId.set(position.instrument.id, position.instrument)
        for (const item of watchlist) byId.set(item.instrument.id, item.instrument)
        for (const candidate of screener) byId.set(candidate.instrument.id, candidate.instrument)
        setInstruments([...byId.values()].sort((a, b) => a.broker_symbol.localeCompare(b.broker_symbol)))
      })
      .catch(() => setInstruments([]))
  }, [])

  async function handleDetect() {
    setDetecting(true)
    setError(null)
    setDetection(null)
    try {
      const result = await api.detectCorporateActions()
      setDetection(result)
      load()
      loadCoverage()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDetecting(false)
    }
  }

  async function handleResume() {
    setResuming(true)
    setResumeError(null)
    try {
      await api.resumeAlphaVantageDetection()
      load()
      loadCoverage()
    } catch (err) {
      setResumeError(err instanceof Error ? err.message : String(err))
    } finally {
      setResuming(false)
    }
  }

  async function handleDetectOne() {
    setCheckingOne(true)
    setOneError(null)
    setOneResult(null)
    try {
      const result = await api.detectCorporateActionOne({ instrumentId: Number(checkInstrumentId), provider: 'eodhd' })
      setOneResult(result)
      if (result.status === 'created') {
        load()
        loadCoverage()
      }
    } catch (err) {
      setOneError(err instanceof Error ? err.message : String(err))
    } finally {
      setCheckingOne(false)
    }
  }

  const ratioNumeratorValue = Number(ratioNumerator.trim().replace(',', '.'))
  const ratioDenominatorValue = Number(ratioDenominator.trim().replace(',', '.'))
  const canSubmit =
    instrumentId !== '' &&
    effectiveDate !== '' &&
    Number.isFinite(ratioNumeratorValue) &&
    ratioNumeratorValue > 0 &&
    Number.isFinite(ratioDenominatorValue) &&
    ratioDenominatorValue > 0

  async function handleCreate() {
    setBusy(true)
    setError(null)
    setDetection(null)
    try {
      await api.createCorporateAction({
        instrument_id: Number(instrumentId),
        action_type: actionType,
        effective_date: effectiveDate,
        ratio_numerator: ratioNumeratorValue,
        ratio_denominator: ratioDenominatorValue,
      })
      setFormOpen(false)
      setInstrumentId('')
      setEffectiveDate('')
      setRatioNumerator('')
      setRatioDenominator('')
      load()
      loadCoverage()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(id: number) {
    try {
      await api.deleteCorporateAction(id)
      load()
      loadCoverage()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const resumeButtonDisabled = resuming || (resumeStatus !== null && resumeStatus.remaining_incomplete === 0)
  const lastRun = resumeStatus?.last_run ?? null

  return (
    <div className="card">
      <h2>{t('corporateActions.title')}</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {t('corporateActions.description')}
      </p>

      {error && <div className="notice error">{error}</div>}

      {/* --- Couverture automatique : lecture seule, jamais d'appel fournisseur --- */}
      {coverage && (
        <div style={{ marginTop: '0.6rem' }}>
          <h3 style={{ marginBottom: '0.2rem' }}>{t('corporateActions.coverageTitle')}</h3>
          <div>{t('corporateActions.coverage.instrumentsEligible', { count: coverage.eligible_instruments })}</div>
          <div className="muted">
            {t('corporateActions.coverage.instrumentsChecked', {
              checked: coverage.checked_instruments,
              unchecked: coverage.unchecked_instruments,
            })}
          </div>
          {coverage.excluded_instruments > 0 && (
            <div className="muted">
              {t('corporateActions.coverage.instrumentsExcluded', { count: coverage.excluded_instruments })}
            </div>
          )}
          <div style={{ marginTop: '0.4rem' }}>
            {(coverage.verified_three_sources_events > 0 || coverage.verified_cross_source_events > 0) && (
              <div>
                {t('corporateActions.coverage.verifiedEvents', {
                  count: coverage.verified_three_sources_events + coverage.verified_cross_source_events,
                })}
              </div>
            )}
            {coverage.candidate_single_source_events > 0 && (
              <div className="muted">
                {t('corporateActions.coverage.candidateEvents', { count: coverage.candidate_single_source_events })}
              </div>
            )}
            {coverage.provider_conflict_events > 0 && (
              <div className="muted">
                {t('corporateActions.coverage.conflictEvents', { count: coverage.provider_conflict_events })}
              </div>
            )}
            {coverage.suspect_ticker_reuse_events > 0 && (
              <div className="muted">
                {t('corporateActions.coverage.suspectEvents', { count: coverage.suspect_ticker_reuse_events })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* --- Alpha Vantage : bouton de reprise ciblée, jamais automatique --- */}
      <div style={{ marginTop: '1rem', paddingTop: '0.8rem', borderTop: '1px solid var(--border)' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('corporateActions.resume.title')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('corporateActions.resume.description')}
        </p>
        <button onClick={() => void handleResume()} disabled={resumeButtonDisabled}>
          {resuming ? t('corporateActions.resume.running') : t('corporateActions.resume.button')}
        </button>

        {resumeError && <div className="notice error" style={{ marginTop: '0.6rem' }}>{resumeError}</div>}

        {resumeStatus && !resuming && (
          <div className="muted" style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
            {resumeStatus.remaining_incomplete > 0
              ? t('corporateActions.resume.remaining', { count: resumeStatus.remaining_incomplete })
              : t('corporateActions.resume.upToDate')}
          </div>
        )}
        {resumeStatus?.enabled === false && (
          <div className="muted" style={{ fontSize: '0.85rem' }}>{t('corporateActions.resume.paused')}</div>
        )}

        {lastRun === null && !resuming && (
          <div className="muted" style={{ fontSize: '0.85rem' }}>{t('corporateActions.resume.neverRun')}</div>
        )}
        {lastRun && (
          <div style={{ marginTop: '0.4rem', fontSize: '0.85rem' }}>
            <div className="muted">{t('corporateActions.resume.lastRun', { date: formatDate(lastRun.started_at) })}</div>
            {lastRun.skipped_reason === null && (
              <div>
                {t('corporateActions.resume.lastRunSummary', {
                  checked: lastRun.checked,
                  verified: lastRun.verified_cross_source + lastRun.verified_three_sources,
                  candidates: lastRun.candidate_single_source,
                  noEvents: lastRun.no_events,
                })}
              </div>
            )}
            {lastRun.rate_limited > 0 && (
              <div className="notice warning" style={{ marginTop: '0.4rem' }}>
                {t('corporateActions.resume.rateLimited')}
              </div>
            )}
          </div>
        )}
      </div>

      {/* --- Candidats à confirmer : jamais appliqués automatiquement --- */}
      <div style={{ marginTop: '1.2rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('corporateActions.outstanding.title')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('corporateActions.outstanding.description')}
        </p>
        {outstanding && outstanding.length === 0 && (
          <div className="empty">{t('corporateActions.outstanding.empty')}</div>
        )}
        {outstanding && outstanding.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('corporateActions.instrument')}</th>
                  <th>{t('corporateActions.type')}</th>
                  <th>{t('corporateActions.date')}</th>
                  <th className="num">{t('corporateActions.ratio')}</th>
                  <th>{t('corporateActions.confidence')}</th>
                </tr>
              </thead>
              <tbody>
                {outstanding.map((candidate, i) => (
                  <tr key={`${candidate.instrument.id}-${candidate.effective_date}-${i}`}>
                    <td>{candidate.instrument.broker_symbol}</td>
                    <td>{t(`corporateActions.type.${candidate.action_type}`)}</td>
                    <td>{formatDate(candidate.effective_date)}</td>
                    <td className="num">
                      {candidate.ratio_numerator}:{candidate.ratio_denominator}
                    </td>
                    <td title={t('corporateActions.outstanding.providers', { providers: candidate.providers.join(', ') })}>
                      <ConfidenceBadge confidence={candidate.confidence} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div style={{ marginTop: '1.2rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
        <button className="primary" onClick={() => void handleDetect()} disabled={detecting}>
          {detecting ? t('common.saving') : t('corporateActions.detect')}
        </button>

        {detection && (
          <div style={{ marginTop: '0.8rem' }}>
            <div>
              {t('corporateActions.detectionChecked', { checked: detection.checked, candidates: detection.candidates })}
            </div>
            {detection.failed > 0 && (
              <div className="muted">{t('corporateActions.detectionFailedSummary', { count: detection.failed })}</div>
            )}
            {detection.not_checked > 0 && (
              <div className="muted">{t('corporateActions.detectionIncomplete', { count: detection.not_checked })}</div>
            )}
            {detection.skipped > 0 && (
              <div className="muted">{t('corporateActions.detectionSkippedSummary', { count: detection.skipped })}</div>
            )}
            {(detection.failed > 0 || detection.not_checked > 0) && (
              <div className="notice warning" style={{ marginTop: '0.6rem' }}>
                {t('corporateActions.detectionFailedCaveat')}
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ marginTop: '1.2rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('corporateActions.detectOne.title')}</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
          {t('corporateActions.detectOne.description')}
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
          <select value={checkInstrumentId} onChange={(e) => setCheckInstrumentId(e.target.value)}>
            <option value="">{t('corporateActions.selectInstrument')}</option>
            {instruments.map((instrument) => (
              <option key={instrument.id} value={instrument.id}>
                {instrument.broker_symbol}
                {instrument.name ? ` — ${instrument.name}` : ''}
              </option>
            ))}
          </select>
          <button disabled={checkInstrumentId === '' || checkingOne} onClick={() => void handleDetectOne()}>
            {checkingOne ? t('common.saving') : t('corporateActions.detectOne.button')}
          </button>
        </div>

        {oneError && <div className="notice error" style={{ marginTop: '0.6rem' }}>{oneError}</div>}
        {oneResult && (
          <div
            className={`notice ${
              oneResult.status === 'created' || oneResult.status === 'already_known'
                ? 'success'
                : oneResult.status === 'no_events'
                  ? 'info'
                  : 'warning'
            }`}
            style={{ marginTop: '0.6rem' }}
          >
            {oneResult.status === 'created' && (
              <div>{t('corporateActions.detectOne.created', { count: oneResult.created })}</div>
            )}
            {oneResult.status === 'already_known' && <div>{t('corporateActions.detectOne.alreadyKnown')}</div>}
            {oneResult.status === 'no_events' && <div>{t('corporateActions.detectOne.noEvents')}</div>}
            {DETECT_ONE_FAILURE_STATUSES.has(oneResult.status) && (
              <>
                <div>{t('corporateActions.detectOne.failed')}</div>
                <div className="muted">{t('corporateActions.detectionFailedCaveat')}</div>
              </>
            )}
          </div>
        )}
      </div>

      <div style={{ marginTop: '1.2rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
        <h3 style={{ marginBottom: '0.2rem' }}>{t('corporateActions.historyTitle')}</h3>
        <div>{t('corporateActions.historyCount', { count: actions?.length ?? 0 })}</div>
        {detection &&
          (detection.created > 0 ? (
            <div className="muted">{t('corporateActions.historyNewEvents', { count: detection.created })}</div>
          ) : (
            <div className="muted">{t('corporateActions.historyNoNewEvents')}</div>
          ))}
        <div style={{ marginTop: '0.6rem' }}>
          <button className="link" onClick={() => setFormOpen((v) => !v)}>
            {formOpen ? t('common.cancel') : t('corporateActions.addManually')}
          </button>
        </div>

        {formOpen && (
          <div style={{ marginTop: '0.6rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
            <select value={instrumentId} onChange={(e) => setInstrumentId(e.target.value)}>
              <option value="">{t('corporateActions.selectInstrument')}</option>
              {instruments.map((instrument) => (
                <option key={instrument.id} value={instrument.id}>
                  {instrument.broker_symbol}
                  {instrument.name ? ` — ${instrument.name}` : ''}
                </option>
              ))}
            </select>
            <select value={actionType} onChange={(e) => setActionType(e.target.value as 'split' | 'reverse_split')}>
              <option value="split">{t('corporateActions.type.split')}</option>
              <option value="reverse_split">{t('corporateActions.type.reverse_split')}</option>
            </select>
            <input type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
            <span style={{ display: 'inline-flex', gap: '0.3rem', alignItems: 'center' }}>
              <input
                style={{ width: '4rem' }}
                placeholder={t('corporateActions.newShares')}
                value={ratioNumerator}
                onChange={(e) => setRatioNumerator(e.target.value)}
              />
              {'for'}
              <input
                style={{ width: '4rem' }}
                placeholder={t('corporateActions.oldShares')}
                value={ratioDenominator}
                onChange={(e) => setRatioDenominator(e.target.value)}
              />
            </span>
            <button className="primary" disabled={!canSubmit || busy} onClick={() => void handleCreate()}>
              {busy ? t('common.saving') : t('common.add')}
            </button>
          </div>
        )}
      </div>

      {actions && actions.length === 0 && <div className="empty">{t('corporateActions.empty')}</div>}

      {actions && actions.length > 0 && (
        <div className="table-wrap" style={{ marginTop: '1rem' }}>
          <table>
            <thead>
              <tr>
                <th>{t('corporateActions.instrument')}</th>
                <th>{t('corporateActions.type')}</th>
                <th>{t('corporateActions.date')}</th>
                <th className="num">{t('corporateActions.ratio')}</th>
                <th>{t('corporateActions.source')}</th>
                <th>{t('corporateActions.confidence')}</th>
                <th>{t('corporateActions.priceHistoryStatus')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {actions.map((action) => (
                <Fragment key={action.id}>
                  <tr>
                    <td>{action.instrument?.broker_symbol ?? '—'}</td>
                    <td>{t(`corporateActions.type.${action.action_type}`)}</td>
                    <td>{formatDate(action.effective_date)}</td>
                    <td className="num">
                      {action.ratio_numerator}:{action.ratio_denominator}
                    </td>
                    <td>{t(`corporateActions.source.${action.source}`)}</td>
                    <td>
                      <button
                        className="link"
                        onClick={() => setExpandedActionId(expandedActionId === action.id ? null : action.id)}
                        title={t('corporateActions.details')}
                      >
                        <ConfidenceBadge confidence={action.confidence} />
                      </button>
                    </td>
                    <td>{t(`corporateActions.status.${action.price_history_status}`)}</td>
                    <td>
                      <button className="link" onClick={() => void handleDelete(action.id)}>
                        {t('common.delete')}
                      </button>
                    </td>
                  </tr>
                  {expandedActionId === action.id && (
                    <tr>
                      <td colSpan={8}>
                        <div className="muted" style={{ fontSize: '0.85rem' }}>
                          <strong>{t('corporateActions.provenance.title')}</strong>
                          <ul style={{ margin: '0.3rem 0 0', paddingLeft: '1.2rem' }}>
                            {(action.corroborating_sources ?? []).map((s, i) => (
                              <li key={i}>
                                {t('corporateActions.provenance.foundOn', {
                                  provider: t(`corporateActions.source.${s.provider}`),
                                  date: formatDate(s.event_date),
                                  ratio: `${s.numerator}:${s.denominator}`,
                                })}
                              </li>
                            ))}
                            {!(action.corroborating_sources ?? []).some((s) => s.provider === 'fmp') && (
                              <li>{t('corporateActions.provenance.notUsedFmp')}</li>
                            )}
                            <li>{t('corporateActions.provenance.notCheckedEodhd')}</li>
                          </ul>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
