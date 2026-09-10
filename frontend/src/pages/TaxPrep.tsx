import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { TaxEnvelopeSummary, TaxYearSummary } from '../api/types'
import { signClass } from '../format'
import { useI18n } from '../i18n'

const ENVELOPE_BADGE_CLASS: Record<string, string> = {
  cto: 'confidence-neutral',
  pea: 'confidence-neutral',
  p2p: 'confidence-neutral',
  employee_savings: 'confidence-neutral',
}

const STATUS_BADGE_CLASS: Record<string, string> = {
  to_reconcile: 'confidence-review',
  not_applicable: 'confidence-neutral',
}

function Fact({ label, value, negative }: { label: string; value: number | null; negative?: boolean }) {
  const { formatNumber } = useI18n()
  if (value === null) return null
  return (
    <div>
      <dt>{label}</dt>
      <dd className={negative ? signClass(value) : undefined}>{formatNumber(value)}</dd>
    </div>
  )
}

function EnvelopeCard({ envelope }: { envelope: TaxEnvelopeSummary }) {
  const { t, formatNumber } = useI18n()

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0 }}>{envelope.account}</h3>
        <span className={`tag ${ENVELOPE_BADGE_CLASS[envelope.envelope_kind] ?? 'confidence-neutral'}`}>
          {t(`taxPrep.envelope.${envelope.envelope_kind}`)}
        </span>
        <span className={`tag ${STATUS_BADGE_CLASS[envelope.status] ?? 'confidence-neutral'}`}>
          {t(`taxPrep.status.${envelope.status}`)}
        </span>
      </div>

      <dl className="position-detail-facts" style={{ marginTop: '0.8rem' }}>
        <Fact label={t('taxPrep.dividendsGross')} value={envelope.dividends_gross} />
        <Fact label={t('taxPrep.dividendsWithholding')} value={envelope.dividends_withholding} negative />
        <Fact label={t('taxPrep.interest')} value={envelope.interest} />
        <Fact label={t('taxPrep.realizedGains')} value={envelope.realized_gains} />
        <Fact label={t('taxPrep.realizedLosses')} value={envelope.realized_losses} negative />
        <Fact label={t('taxPrep.fees')} value={envelope.fees} negative />
        <Fact label={t('taxPrep.deposits')} value={envelope.deposits} />
        <Fact label={t('taxPrep.withdrawals')} value={envelope.withdrawals} negative />
      </dl>

      {envelope.unmatched_sales_count > 0 && (
        <p className="notice warning" style={{ marginTop: '0.8rem' }}>
          {t('taxPrep.unmatchedSalesLine', {
            count: envelope.unmatched_sales_count,
            amount: formatNumber(envelope.unmatched_sales_amount ?? 0),
          })}
        </p>
      )}

      {envelope.other_flows.length > 0 && (
        <>
          <h4 style={{ marginBottom: '0.3rem' }}>{t('taxPrep.otherFlows')}</h4>
          <ul className="attention-list">
            {envelope.other_flows.map((flow, i) => (
              <li key={i} className="attention-item">
                {flow.label} — <span className={signClass(flow.amount)}>{formatNumber(flow.amount)}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {envelope.notes.map((note, i) => (
        <p key={i} className="notice info" style={{ marginTop: '0.6rem' }}>
          {t(note.code, note.params)}
        </p>
      ))}
    </div>
  )
}

/**
 * Annual tax-year reconciliation summary, by account/envelope — a
 * reconciliation aid, never a tax calculation. Every figure here is a plain
 * sum of already-imported transactions; no rate is ever applied, and the
 * permanent disclaimer at the top is never dismissible. See DEVLOG
 * "Decision 3u.60".
 */
export function TaxPrep() {
  const { t } = useI18n()
  const [years, setYears] = useState<number[] | null>(null)
  const [year, setYear] = useState<number | null>(null)
  const [summary, setSummary] = useState<TaxYearSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getTaxYears()
      .then((res) => {
        setYears(res.years)
        setYear(res.years[0] ?? new Date().getFullYear())
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const loadSummary = useCallback(() => {
    if (year === null) return
    api
      .getTaxSummary(year)
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [year])

  useEffect(loadSummary, [loadSummary])

  return (
    <>
      <div className="page-header">
        <h1>{t('taxPrep.title')}</h1>
        <p>{t('taxPrep.subtitle')}</p>
      </div>

      {error && <div className="notice error">{error}</div>}

      {summary && <div className="notice info">{t(summary.disclaimer.code, summary.disclaimer.params)}</div>}

      {years && years.length === 0 && <div className="empty">{t('taxPrep.empty')}</div>}

      {years && years.length > 0 && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '0.5rem' }}>
            <label htmlFor="tax-year-select" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              {t('taxPrep.yearLabel')}
              <select
                id="tax-year-select"
                value={year ?? ''}
                onChange={(e) => setYear(Number(e.target.value))}
              >
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </label>
            {year !== null && (
              <a className="link" href={`/api/tax/summary.csv?year=${year}`} download>
                {t('taxPrep.exportCsv')}
              </a>
            )}
          </div>
        </div>
      )}

      {summary && summary.envelopes.length === 0 && <div className="empty">{t('taxPrep.emptyYear')}</div>}

      {summary && summary.envelopes.map((envelope) => <EnvelopeCard key={envelope.account} envelope={envelope} />)}
    </>
  )
}
