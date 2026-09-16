import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { DividendDetailRow, DividendSummaryRow } from '../api/types'
import { useI18n } from '../i18n'

function accountLabel(account: string | null, t: (key: string) => string): string {
  return account ?? t('dividends.unknownAccount')
}

function currencyLabel(currency: string | null, t: (key: string) => string): string {
  return currency ?? t('dividends.unknownCurrency')
}

/** One line per currency present in `rows` for the given field — never a
 * single summed value once more than one currency is involved (see
 * DEVLOG "Decision 3u.70": summing raw amounts across currencies silently
 * treats 1 EUR as equal to 1 USD). Falls back to a bare number when only
 * one currency is present, which is the common case. */
function byCurrency(
  rows: DividendSummaryRow[],
  field: 'gross' | 'withholding_tax' | 'net',
  t: (key: string) => string,
  formatNumber: (value: number) => string,
): string {
  const totals = new Map<string | null, number>()
  for (const row of rows) {
    totals.set(row.currency, (totals.get(row.currency) ?? 0) + row[field])
  }
  const entries = [...totals.entries()].sort((a, b) => (a[0] ?? '').localeCompare(b[0] ?? ''))
  if (entries.length <= 1) {
    return formatNumber(entries[0]?.[1] ?? 0)
  }
  return entries.map(([currency, value]) => `${formatNumber(value)} ${currencyLabel(currency, t)}`).join(' + ')
}

/**
 * Dividends received, by calendar year and account — the gap a beginner-user
 * UX review flagged: the Transactions page already sums dividends/
 * withholding globally, but not split by account (PEA and a brokerage
 * account have completely different French tax treatment) or by year (what
 * a declaration needs). Purely descriptive: this never computes a tax
 * liability, only what was actually received and withheld — see DEVLOG
 * "Decision 3u.28".
 *
 * Reachable from Transactions rather than the main nav, matching the scope
 * confirmed with the user: a sub-view, not a new top-level section.
 */
export function Dividends() {
  const { t, formatNumber, formatDate } = useI18n()
  const [summary, setSummary] = useState<DividendSummaryRow[] | null>(null)
  const [detail, setDetail] = useState<DividendDetailRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [yearFilter, setYearFilter] = useState('')
  const [accountFilter, setAccountFilter] = useState('')

  const loadSummary = useCallback(() => {
    api.getDividendSummary().then(setSummary).catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  const loadDetail = useCallback(() => {
    api
      .getDividendDetail({
        year: yearFilter ? Number(yearFilter) : undefined,
        account: accountFilter || undefined,
      })
      .then(setDetail)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [yearFilter, accountFilter])

  useEffect(loadSummary, [loadSummary])
  useEffect(loadDetail, [loadDetail])

  const years = useMemo(
    () => [...new Set((summary ?? []).map((r) => r.year))].sort((a, b) => b - a),
    [summary],
  )
  const accounts = useMemo(
    () => [...new Set((summary ?? []).map((r) => r.account).filter((a): a is string => a !== null))].sort(),
    [summary],
  )

  const latestYear = years[0]
  const heroRows = (summary ?? []).filter((r) => r.year === latestYear)
  const heroPayments = heroRows.reduce((sum, r) => sum + r.payment_count, 0)
  const heroAccountCount = new Set(heroRows.map((r) => r.account)).size

  return (
    <>
      <div className="page-header">
        <h1>{t('dividends.title')}</h1>
        <p>{t('dividends.subtitle')}</p>
      </div>

      {error && <div className="notice error">{error}</div>}

      <div className="notice info">{t('dividends.disclaimer')}</div>

      {summary && summary.length === 0 && <div className="empty">{t('dividends.empty')}</div>}

      {summary && summary.length > 0 && latestYear !== undefined && (
        <div className="stat-grid" style={{ marginBottom: '1.1rem' }}>
          <div className="stat">
            <div className="label">{t('dividends.heroTitle', { year: latestYear })}</div>
            <div className="value">{byCurrency(heroRows, 'gross', t, formatNumber)}</div>
          </div>
          <div className="stat">
            <div className="label">{t('dividends.withholding')}</div>
            <div className="value">{byCurrency(heroRows, 'withholding_tax', t, formatNumber)}</div>
          </div>
          <div className="stat">
            <div className="label">{t('dividends.net')}</div>
            <div className="value">{byCurrency(heroRows, 'net', t, formatNumber)}</div>
          </div>
          <div className="stat">
            <div className="label">{t('dividends.paymentCount')}</div>
            <div className="value">{heroPayments}</div>
          </div>
          <div className="stat">
            <div className="label">{t('dividends.accountsAnalyzed')}</div>
            <div className="value">{heroAccountCount}</div>
          </div>
        </div>
      )}

      {summary && summary.length > 0 && (
        <div className="card">
          <h2>{t('dividends.byYearAccount')}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('dividends.year')}</th>
                  <th>{t('dividends.account')}</th>
                  <th>{t('dividends.currency')}</th>
                  <th className="num">{t('dividends.gross')}</th>
                  <th className="num">{t('dividends.withholding')}</th>
                  <th className="num">{t('dividends.net')}</th>
                  <th className="num">{t('dividends.paymentCount')}</th>
                </tr>
              </thead>
              <tbody>
                {summary.map((row) => (
                  <tr key={`${row.year}-${row.account}-${row.currency}`}>
                    <td>{row.year}</td>
                    <td>{accountLabel(row.account, t)}</td>
                    <td>{currencyLabel(row.currency, t)}</td>
                    <td className="num">{formatNumber(row.gross)}</td>
                    <td className="num">{formatNumber(row.withholding_tax)}</td>
                    <td className="num">{formatNumber(row.net)}</td>
                    <td className="num">{row.payment_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <a className="link" href="/api/dividends/summary.csv" download>
            {t('dividends.exportSummaryCsv')}
          </a>
        </div>
      )}

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '0.5rem' }}>
          <h2>{t('dividends.detailTitle')}</h2>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <select value={yearFilter} onChange={(e) => setYearFilter(e.target.value)}>
              <option value="">{t('dividends.allYears')}</option>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            <select value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)}>
              <option value="">{t('dividends.allAccounts')}</option>
              {accounts.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>
        </div>

        {detail && detail.length === 0 && <div className="empty">{t('dividends.detailEmpty')}</div>}

        {detail && detail.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('dividends.date')}</th>
                  <th>{t('dividends.instrument')}</th>
                  <th>{t('dividends.account')}</th>
                  <th className="num">{t('dividends.gross')}</th>
                  <th className="num">{t('dividends.withholding')}</th>
                  <th className="num">{t('dividends.net')}</th>
                  <th>{t('dividends.reconciliation')}</th>
                </tr>
              </thead>
              <tbody>
                {detail.map((row) => (
                  <tr key={row.id}>
                    <td>{formatDate(row.executed_at)}</td>
                    <td>{row.instrument?.broker_symbol ?? '—'}</td>
                    <td>{accountLabel(row.account, t)}</td>
                    <td className="num">{row.gross !== null ? formatNumber(row.gross) : '—'}</td>
                    <td className="num">{row.withholding_tax !== null ? formatNumber(row.withholding_tax) : '—'}</td>
                    <td className="num">
                      {row.net !== null && row.reconciliation_status !== 'unmatched_tax' ? formatNumber(row.net) : '—'}
                    </td>
                    <td>
                      <span
                        className={`tag ${
                          row.reconciliation_status === 'unmatched_tax'
                            ? 'unresolved'
                            : row.reconciliation_status === 'matched'
                              ? 'confidence-confirmed'
                              : 'neutral'
                        }`}
                      >
                        {t(`dividends.status.${row.reconciliation_status}`)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <a
          className="link"
          href={`/api/dividends/detail.csv${
            yearFilter || accountFilter
              ? `?${new URLSearchParams({ ...(yearFilter && { year: yearFilter }), ...(accountFilter && { account: accountFilter }) }).toString()}`
              : ''
          }`}
          download
        >
          {t('dividends.exportDetailCsv')}
        </a>
      </div>
    </>
  )
}
