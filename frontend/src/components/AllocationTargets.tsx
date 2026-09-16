import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AllocationRow } from '../api/types'
import { useI18n } from '../i18n'

function labelFor(category: string, t: (key: string) => string): string {
  if (category === 'UNKNOWN') return t('breakdown.unknown')
  const key = `breakdown.category.${category}`
  const translated = t(key)
  return translated === key ? category : translated
}

/**
 * Current allocation by asset class vs. a user-configured target range —
 * descriptive only, same "comments on the gap, never suggests a trade"
 * posture as the rest of this app (DEVLOG "Decision 3u.15"). Self-contained,
 * same pattern as `PortfolioBreakdown` (own fetch, no props from the page).
 */
export function AllocationTargets() {
  const { t, formatNumber } = useI18n()
  const [rows, setRows] = useState<AllocationRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editingCategory, setEditingCategory] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState({ min: '', max: '' })
  const [rowBusy, setRowBusy] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)

  function load() {
    setError(null)
    api
      .getAllocation()
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(load, [])

  function startEdit(row: AllocationRow) {
    setEditingCategory(row.category)
    setEditDraft({
      min: row.min_pct !== null ? String(row.min_pct) : '',
      max: row.max_pct !== null ? String(row.max_pct) : '',
    })
    setRowError(null)
  }

  function cancelEdit() {
    setEditingCategory(null)
    setRowError(null)
  }

  async function saveEdit(category: string) {
    const min = Number(editDraft.min.trim().replace(',', '.'))
    const max = Number(editDraft.max.trim().replace(',', '.'))
    if (!Number.isFinite(min) || !Number.isFinite(max) || min < 0 || max > 100 || min > max) {
      setRowError(t('allocation.invalidRange'))
      return
    }
    setRowBusy(true)
    setRowError(null)
    try {
      const updated = await api.setAllocationTarget(category, { min_pct: min, max_pct: max })
      setRows((prev) => (prev ?? []).map((r) => (r.category === category ? updated : r)))
      setEditingCategory(null)
    } catch (err) {
      setRowError(err instanceof Error ? err.message : String(err))
    } finally {
      setRowBusy(false)
    }
  }

  async function removeTarget(category: string) {
    try {
      await api.deleteAllocationTarget(category)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="card">
      <h2>{t('allocation.title')}</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {t('allocation.description')}
      </p>

      {error && <div className="notice error">{error}</div>}
      {rowError && <div className="notice error">{rowError}</div>}

      {rows && rows.length === 0 && <div className="empty">{t('allocation.empty')}</div>}

      {rows && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('allocation.category')}</th>
                <th className="num">{t('allocation.current')}</th>
                <th className="num">{t('allocation.target')}</th>
                <th className="num" title={t('allocation.gapTooltip')}>
                  {t('allocation.gap')}
                </th>
                <th />
                <th>{t('allocation.amount')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.category}>
                  <td>{labelFor(row.category, t)}</td>
                  <td className="num">
                    {formatNumber(row.current_value)} · {formatNumber(row.current_pct, 1)}%
                  </td>
                  <td className="num">
                    {editingCategory === row.category ? (
                      <span style={{ display: 'inline-flex', gap: '0.3rem', alignItems: 'center' }}>
                        <input
                          style={{ width: '4rem', textAlign: 'right' }}
                          value={editDraft.min}
                          onChange={(e) => setEditDraft({ ...editDraft, min: e.target.value })}
                        />
                        {'–'}
                        <input
                          style={{ width: '4rem', textAlign: 'right' }}
                          value={editDraft.max}
                          onChange={(e) => setEditDraft({ ...editDraft, max: e.target.value })}
                        />
                        %
                      </span>
                    ) : row.min_pct !== null && row.max_pct !== null ? (
                      `${formatNumber(row.min_pct, 1)}–${formatNumber(row.max_pct, 1)}%`
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="num">
                    <span
                      className={`tag ${row.state === 'within' ? 'confidence-confirmed' : row.state === 'no_target' ? 'neutral' : 'unresolved'}`}
                    >
                      {t(`allocation.state.${row.state}`)}
                      {row.state !== 'within' && row.state !== 'no_target' ? ` (${formatNumber(row.gap_pct, 1)} pts)` : ''}
                    </span>
                  </td>
                  {/* Actions come right after the compact Status column, not
                      after the free-text "amount to reach minimum" column
                      below — that one can run to a full sentence, which
                      pushed Edit/Delete/Set target far enough right that a
                      real user had to notice the table scrolls horizontally
                      before finding them at all. */}
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {editingCategory === row.category ? (
                      <>
                        <button className="link" disabled={rowBusy} onClick={() => void saveEdit(row.category)}>
                          {rowBusy ? t('common.saving') : t('common.save')}
                        </button>{' '}
                        <button className="link" disabled={rowBusy} onClick={cancelEdit}>
                          {t('common.cancel')}
                        </button>
                      </>
                    ) : (
                      <>
                        <button className="link" onClick={() => startEdit(row)}>
                          {row.state === 'no_target' ? t('allocation.setTarget') : t('common.edit')}
                        </button>
                        {row.state !== 'no_target' && (
                          <>
                            {' '}
                            <button className="link" onClick={() => void removeTarget(row.category)}>
                              {t('common.delete')}
                            </button>
                          </>
                        )}
                      </>
                    )}
                  </td>
                  <td className="muted">
                    {row.state === 'under' && row.amount_to_reach_min !== null
                      ? t('allocation.amountToInvest', { amount: formatNumber(row.amount_to_reach_min) })
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
