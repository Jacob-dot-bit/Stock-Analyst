import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { DividendDetailRow, DividendSummaryRow } from '../api/types'
import { signClass } from '../format'
import { useI18n } from '../i18n'

function accountLabel(account: string | null, t: (key: string) => string): string {
  return account ?? t('dividends.unknownAccount')
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
  const hero = heroRows.reduce(
    (acc, r) => ({
      gross: acc.gross + r.gross,
      withholding: acc.withholding + r.withholding_tax,
      net: acc.net + r.net,
      payments: acc.payments + r.payment_count,
    }),
    { gross: 0, withholding: 0, net: 0, payments: 0 },
  )

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
            <div className="value">{formatNumber(hero.gross)}</div>
          </div>
          <div className="stat">
            <div className="label">{t('dividends.withholding')}</div>
            <div className={`value ${signClass(hero.withholding)}`}>{formatNumber(hero.withholding)}</div>
          </div>
          <div className="stat">
            <div className="label">{t('dividends.net')}</div>
            <div className="value">{formatNumber(hero.net)}</div>
          </div>
          <div className="stat">
            <div className="label">{t('dividends.paymentCount')}</div>
            <div className="value">{hero.payments}</div>
          </div>
          <div className="stat">
            <div className="label">{t('dividends.accountsAnalyzed')}</div>
            <div className="value">{heroRows.length}</div>
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
                  <th className="num">{t('dividends.gross')}</th>
                  <th className="num">{t('dividends.withholding')}</th>
                  <th className="num">{t('dividends.net')}</th>
                  <th className="num">{t('dividends.paymentCount')}</th>
                </tr>
              </thead>
              <tbody>
                {summary.map((row) => (
                  <tr key={`${row.year}-${row.account}`}>
                    <td>{row.year}</td>
                    <td>{accountLabel(row.account, t)}</td>
                    <td className="num">{formatNumber(row.gross)}</td>
                    <td className={`num ${signClass(row.withholding_tax)}`}>{formatNumber(row.withholding_tax)}</td>
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
                    <td className={`num ${row.withholding_tax !== null ? signClass(row.withholding_tax) : ''}`}>
                      {row.withholding_tax !== null ? formatNumber(row.withholding_tax) : '—'}
                    </td>
                    <td className="num">{row.net !== null ? formatNumber(row.net) : '—'}</td>
                    <td>
                      <span
                        className={`tag ${
                          row.reconciliation_status === 'unmatched_tax'
                            ? 'unresolved'
                            : row.reconciliation_status === 'matched'
                              ? 'resolved'
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
