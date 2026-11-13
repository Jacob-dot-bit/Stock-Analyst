import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { errorMessage, useApiResource } from '../hooks/useApiResource'
import type { TaxCapitalGainsYear, TaxEnvelopeSummary, TaxNotice, TaxSaleGain, TaxYearSummary } from '../api/types'
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
        <h2 className="compact" style={{ margin: 0 }}>
          {envelope.account}
        </h2>
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
        <Fact label={t('taxPrep.pmpGains')} value={envelope.pmp_gains} />
        <Fact label={t('taxPrep.pmpLosses')} value={envelope.pmp_losses} negative />
        <Fact label={t('taxPrep.fees')} value={envelope.fees} negative />
        <Fact label={t('taxPrep.deposits')} value={envelope.deposits} />
        <Fact label={t('taxPrep.withdrawals')} value={envelope.withdrawals} negative />
      </dl>

      {envelope.unmatched_sales_count > 0 && (
        <p className="notice warning" style={{ marginTop: '0.8rem' }}>
          {t('taxPrep.unmatchedSalesLine', {
            count: envelope.unmatched_sales_count,
            amount: formatNumber(envelope.unmatched_sales_amount ?? 0),
          })}{' '}
          {Object.entries(envelope.unmatched_reasons)
            .map(([reason, count]) => t(`taxPrep.unmatchedReason.${reason}`, { count }))
            .join(' · ')}
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

      {/* The unmatched-sales note says what the warning above already says. */}
      {envelope.notes.filter((note) => note.code !== 'taxPrep.unmatchedSales').map((note, i) => (
        <p key={i} className="notice info" style={{ marginTop: '0.6rem' }}>
          {t(note.code, note.params)}
        </p>
      ))}
    </div>
  )
}

function lossMap(map: Record<string, number>, formatNumber: (v: number) => string): string {
  return Object.entries(map)
    .map(([origin, amount]) => `${formatNumber(amount)} (${origin})`)
    .join(' · ')
}

/** Gains on CTO sales by the weighted average price, over every ordinary
 * account, with losses carried in from up to ten earlier years (Step
 * 3u.110). Sales whose purchase is not on file are listed, never guessed. */
function CapitalGainsCard({ gains, sales }: { gains: TaxCapitalGainsYear; sales: TaxSaleGain[] }) {
  const { t, formatNumber, formatDate } = useI18n()
  const carriedIn = lossMap(gains.losses_carried_in, formatNumber)
  const carriedOut = lossMap(gains.losses_carried_out, formatNumber)
  return (
    <div className="card">
      <h2 className="compact">{t('taxPrep.gains.title', { year: gains.year })}</h2>
      <p className="budget-hint">{t('taxPrep.gains.hint')}</p>
      <dl className="position-detail-facts" style={{ marginTop: '0.8rem' }}>
        <Fact label={t('taxPrep.gains.gains')} value={gains.gains} />
        <Fact label={t('taxPrep.gains.losses')} value={gains.losses} negative />
        <Fact label={t('taxPrep.gains.net')} value={gains.net} negative />
        {carriedIn && (
          <div>
            <dt>{t('taxPrep.gains.carriedIn')}</dt>
            <dd>{carriedIn}</dd>
          </div>
        )}
        {gains.losses_used > 0 && <Fact label={t('taxPrep.gains.used')} value={gains.losses_used} />}
        <Fact label={t('taxPrep.gains.taxable')} value={gains.taxable_net} />
        {carriedOut && (
          <div>
            <dt>{t('taxPrep.gains.carriedOut')}</dt>
            <dd>{carriedOut}</dd>
          </div>
        )}
      </dl>
      {gains.unmatched_sales > 0 && (
        <p className="notice warning" style={{ marginTop: '0.8rem' }}>
          {t('taxPrep.gains.unmatched', { count: gains.unmatched_sales })}
        </p>
      )}
      {sales.length > 0 && (
        <details style={{ marginTop: '0.8rem' }}>
          <summary>{t('taxPrep.gains.sales', { count: sales.length })}</summary>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('taxPrep.gains.col.date')}</th>
                  <th>{t('taxPrep.gains.col.account')}</th>
                  <th>{t('taxPrep.gains.col.symbol')}</th>
                  <th className="num">{t('taxPrep.gains.col.units')}</th>
                  <th className="num">{t('taxPrep.gains.col.proceeds')}</th>
                  <th className="num">{t('taxPrep.gains.col.cost')}</th>
                  <th className="num">{t('taxPrep.gains.col.gain')}</th>
                </tr>
              </thead>
              <tbody>
                {sales.map((sale) => (
                  <tr key={sale.transaction_id}>
                    <td>{formatDate(sale.executed_at)}</td>
                    <td>{sale.account}</td>
                    <td>{sale.symbol ?? '—'}</td>
                    <td className="num">{sale.units === null ? '—' : formatNumber(sale.units, 4)}</td>
                    <td className="num">{formatNumber(sale.proceeds)}</td>
                    <td className="num">{sale.cost === null ? '—' : formatNumber(sale.cost)}</td>
                    <td className={`num ${sale.gain === null ? 'muted' : signClass(sale.gain)}`}>
                      {sale.gain === null
                        ? t(`taxPrep.unmatchedReason.${sale.unmatched_reason}`, { count: 1 })
                        : formatNumber(sale.gain)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  )
}

/** What the tax office worked out for the year (Step 3u.109): the named
 * figures, then every amount line of the notice, folded away. */
function TaxNoticeCard({ notice }: { notice: TaxNotice }) {
  const { t, formatNumber } = useI18n()
  const f = notice.figures
  return (
    <div className="card">
      <h2 className="compact">{t('taxPrep.notice.title', { year: notice.income_year })}</h2>
      <dl className="position-detail-facts" style={{ marginTop: '0.8rem' }}>
        <Fact label={t('taxPrep.notice.grossIncome')} value={f.gross_income} />
        <Fact label={t('taxPrep.notice.taxableIncome')} value={f.taxable_income} />
        <Fact label={t('taxPrep.notice.referenceIncome')} value={f.reference_income} />
        <Fact label={t('taxPrep.notice.scaleTax')} value={f.scale_tax} />
        <Fact label={t('taxPrep.notice.netTax')} value={f.net_tax} />
        <Fact label={t('taxPrep.notice.taxDue')} value={f.tax_due} />
        <Fact label={t('taxPrep.notice.balance')} value={f.balance} />
        {f.withholding_rate !== null && (
          <div>
            <dt>{t('taxPrep.notice.rate')}</dt>
            <dd>{formatNumber(f.withholding_rate)} %</dd>
          </div>
        )}
        {f.retirement_ceiling.length > 0 && (
          <div>
            <dt>{t('taxPrep.notice.ceiling')}</dt>
            <dd>{f.retirement_ceiling.map((v) => formatNumber(v, 0)).join(' · ')}</dd>
          </div>
        )}
      </dl>
      <details style={{ marginTop: '0.8rem' }}>
        <summary>{t('taxPrep.notice.lines')}</summary>
        <div className="table-wrap">
          <table>
            <tbody>
              {notice.lines.map((line, i) => (
                <tr key={i}>
                  <td className="muted">{line.section}</td>
                  <td>{line.label}</td>
                  <td className="num">{line.values.map((v) => formatNumber(v, 0)).join(' · ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
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
  const [yearsError, setYearsError] = useState<string | null>(null)
  const [notices, setNotices] = useState<TaxNotice[]>([])

  useEffect(() => {
    // A notice can cover a year with no imported transaction: its year is
    // offered too.
    Promise.all([api.getTaxYears(), api.getTaxNotices().catch(() => [] as TaxNotice[])])
      .then(([res, found]) => {
        const all = [...new Set([...res.years, ...found.map((n) => n.income_year)])].sort((a, b) => b - a)
        setNotices(found)
        setYears(all)
        setYear(all[0] ?? new Date().getFullYear())
      })
      .catch((err) => setYearsError(errorMessage(err)))
  }, [])
  const notice = notices.find((n) => n.income_year === year)

  const summaryResource = useApiResource<TaxYearSummary | null>(
    () => (year === null ? Promise.resolve(null) : api.getTaxSummary(year)),
    [year],
  )
  const summary = summaryResource.data
  const error = yearsError ?? summaryResource.error

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

      {notice && <TaxNoticeCard notice={notice} />}
      {!notice && year !== null && years && years.length > 0 && (
        <p className="budget-hint">{t('taxPrep.notice.none', { year })}</p>
      )}

      {summary?.capital_gains && <CapitalGainsCard gains={summary.capital_gains} sales={summary.sales} />}

      {summary && summary.envelopes.length === 0 && <div className="empty">{t('taxPrep.emptyYear')}</div>}

      {summary && summary.envelopes.map((envelope) => <EnvelopeCard key={envelope.account} envelope={envelope} />)}
    </>
  )
}
