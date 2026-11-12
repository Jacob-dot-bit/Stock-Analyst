import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { BudgetMonth, BudgetOperations, BudgetSummary } from '../api/types'
import { SkeletonCards } from '../components/Skeleton'
import { useI18n } from '../i18n'

const INCOME_CATEGORIES = new Set(['salary', 'benefits', 'health_refund', 'interest', 'other_income'])

function signClass(value: number): string | undefined {
  if (value > 0.005) return 'budget-pos'
  if (value < -0.005) return 'budget-neg'
  return undefined
}

/**
 * My bank accounts as a budget: what comes in, what goes out by category,
 * what goes to the brokers. Everything is computed by the backend from the
 * bank export (`app/budget/`); this page only lays it out. Periods count
 * back from the last operation on file, not from today. See DEVLOG
 * "Step 3u.92".
 */
export function Budget() {
  const { t, locale, formatNumber, formatDate } = useI18n()
  const [summary, setSummary] = useState<BudgetSummary | null>(null)
  const [operations, setOperations] = useState<BudgetOperations | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [category, setCategory] = useState('')
  const [days, setDays] = useState(60)

  useEffect(() => {
    api
      .getBudgetSummary(12)
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  useEffect(() => {
    api
      .getBudgetOperations({ days, category: category || undefined })
      .then(setOperations)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [days, category])

  const months = summary?.months ?? []
  const lastFull = [...months].reverse().find((m) => !m.partial) ?? months[months.length - 1]
  const month: BudgetMonth | undefined = months.find((m) => m.month === selected) ?? lastFull

  const spendingRows = useMemo(() => {
    if (!month) return []
    return Object.entries(month.categories)
      .filter(([name]) => !INCOME_CATEGORIES.has(name))
      .sort((a, b) => b[1] - a[1])
  }, [month])
  const maxSpending = Math.max(1, ...spendingRows.map(([, value]) => value))

  const categoryLabel = (name: string) => t(`budget.category.${name}`)
  const monthLabel = (key: string) => {
    const [year, mon] = key.split('-').map(Number)
    return new Date(year, mon - 1, 1).toLocaleDateString(locale, { month: 'long', year: 'numeric' })
  }

  return (
    <>
      <div className="page-header">
        <h1>{t('budget.title')}</h1>
        <p>{t('budget.subtitle')}</p>
        {summary?.as_of && (
          <div className="page-header-meta">
            {t('budget.asOf', { date: formatDate(summary.as_of), accounts: summary.accounts.join(', ') })}
          </div>
        )}
      </div>

      {error && <div className="notice error">{error}</div>}
      {!summary && !error && <SkeletonCards />}
      {summary && months.length === 0 && <div className="empty">{t('budget.empty')}</div>}

      {summary?.averages && (
        <div className="stat-grid" style={{ marginBottom: 'var(--space-5)' }}>
          <div className="stat">
            <div className="label">{t('budget.avgIncome', { count: summary.averages.months })}</div>
            <div className="value">{formatNumber(summary.averages.income)}</div>
          </div>
          <div className="stat">
            <div className="label">{t('budget.avgSpending', { count: summary.averages.months })}</div>
            <div className="value">{formatNumber(summary.averages.spending)}</div>
          </div>
          <div className="stat">
            <div className="label">{t('budget.avgNet', { count: summary.averages.months })}</div>
            <div className={`value ${signClass(summary.averages.net) ?? ''}`}>{formatNumber(summary.averages.net)}</div>
          </div>
          <div className="stat">
            <div className="label">{t('budget.avgInvested', { count: summary.averages.months })}</div>
            <div className="value">{formatNumber(summary.averages.invested)}</div>
          </div>
        </div>
      )}

      {months.length > 0 && (
        <div className="card">
          <h2>{t('budget.byMonth')}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('budget.month')}</th>
                  <th className="num">{t('budget.income')}</th>
                  <th className="num">{t('budget.spending')}</th>
                  <th className="num">{t('budget.net')}</th>
                  <th className="num">{t('budget.invested')}</th>
                </tr>
              </thead>
              <tbody>
                {[...months].reverse().map((m) => (
                  <tr
                    key={m.month}
                    className={m.month === month?.month ? 'budget-selected' : undefined}
                    onClick={() => setSelected(m.month)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td>
                      {monthLabel(m.month)}
                      {m.partial && <span className="budget-partial"> · {t('budget.partial')}</span>}
                    </td>
                    <td className="num">{formatNumber(m.income)}</td>
                    <td className="num">{formatNumber(m.spending)}</td>
                    <td className={`num ${signClass(m.net) ?? ''}`}>{formatNumber(m.net)}</td>
                    <td className="num">{formatNumber(m.invested)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="budget-hint">{t('budget.monthHint')}</p>
        </div>
      )}

      {month && spendingRows.length > 0 && (
        <div className="card">
          <h2>{t('budget.categoriesOf', { month: monthLabel(month.month) })}</h2>
          <div className="budget-bars">
            {spendingRows.map(([name, value]) => (
              <div className="budget-bar-row" key={name}>
                <span className="budget-bar-label">{categoryLabel(name)}</span>
                <span className="budget-bar-track">
                  <span className="budget-bar-fill" style={{ width: `${Math.max(0, (value / maxSpending) * 100)}%` }} />
                </span>
                <span className={`budget-bar-value num ${value < 0 ? 'budget-pos' : ''}`}>{formatNumber(value)}</span>
                <span className="budget-bar-avg num">
                  {summary?.averages?.categories[name] !== undefined
                    ? t('budget.avgShort', { value: formatNumber(summary.averages.categories[name]) })
                    : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {summary && summary.recurring.length > 0 && (
        <div className="card">
          <h2>{t('budget.recurring')}</h2>
          <p className="budget-hint">
            {t('budget.recurringTotal', {
              value: formatNumber(summary.recurring.reduce((sum, r) => sum + r.monthly, 0)),
            })}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('budget.merchant')}</th>
                  <th>{t('budget.category')}</th>
                  <th className="num">{t('budget.perMonth')}</th>
                  <th>{t('budget.last')}</th>
                </tr>
              </thead>
              <tbody>
                {summary.recurring.map((r) => (
                  <tr key={r.merchant}>
                    <td>{r.merchant}</td>
                    <td>{categoryLabel(r.category)}</td>
                    <td className="num">{formatNumber(r.monthly)}</td>
                    <td>{formatDate(r.last)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {summary && summary.top_merchants.length > 0 && (
        <div className="card">
          <h2>{t('budget.topMerchants')}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('budget.merchant')}</th>
                  <th>{t('budget.category')}</th>
                  <th className="num">{t('budget.total')}</th>
                  <th className="num">{t('budget.count')}</th>
                </tr>
              </thead>
              <tbody>
                {summary.top_merchants.map((m) => (
                  <tr key={m.merchant}>
                    <td>{m.merchant}</td>
                    <td>{categoryLabel(m.category)}</td>
                    <td className="num">{formatNumber(m.total)}</td>
                    <td className="num">{m.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {summary && summary.to_sort.length > 0 && (
        <div className="card">
          <h2>{t('budget.toSort')}</h2>
          <p className="budget-hint">{t('budget.toSortHint')}</p>
          <div className="table-wrap">
            <table>
              <tbody>
                {summary.to_sort.map((m) => (
                  <tr key={m.merchant}>
                    <td>{m.merchant}</td>
                    <td className="num">{formatNumber(m.total)}</td>
                    <td className="num">{m.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {months.length > 0 && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '0.5rem' }}>
            <h2>{t('budget.operations')}</h2>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <select aria-label={t('budget.category')} value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">{t('budget.allCategories')}</option>
                {Object.keys(summary?.averages?.categories ?? {})
                  .concat(['investment', 'internal'])
                  .sort((a, b) => categoryLabel(a).localeCompare(categoryLabel(b)))
                  .map((name) => (
                    <option key={name} value={name}>
                      {categoryLabel(name)}
                    </option>
                  ))}
              </select>
              <select aria-label={t('budget.period')} value={days} onChange={(e) => setDays(Number(e.target.value))}>
                {[30, 60, 90, 180, 365].map((d) => (
                  <option key={d} value={d}>
                    {t('budget.lastDays', { count: d })}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {operations && operations.operations.length === 0 && <div className="empty">{t('budget.noOperations')}</div>}
          {operations && operations.operations.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t('budget.date')}</th>
                    <th>{t('budget.merchant')}</th>
                    <th>{t('budget.category')}</th>
                    <th>{t('budget.account')}</th>
                    <th className="num">{t('budget.amount')}</th>
                  </tr>
                </thead>
                <tbody>
                  {operations.operations.map((op) => (
                    <tr key={op.id} className={op.kind === 'internal' || op.kind === 'investment' ? 'budget-muted' : undefined}>
                      <td>{formatDate(op.date)}</td>
                      <td>{op.merchant}</td>
                      <td>{categoryLabel(op.category)}</td>
                      <td>{op.account}</td>
                      <td className={`num ${signClass(op.amount) ?? ''}`}>{formatNumber(op.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  )
}
