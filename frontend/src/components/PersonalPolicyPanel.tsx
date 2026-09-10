import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type {
  PersonalPolicy,
  PersonalPolicyDraft,
  PersonalPolicyGap,
  PersonalPolicyLimit,
  PersonalPolicyLimitDimension,
} from '../api/types'
import { useI18n } from '../i18n'

const LIMIT_DIMENSIONS: PersonalPolicyLimitDimension[] = ['line', 'sector', 'country', 'currency', 'category', 'declared_valuation']

//: "line" and "declared_valuation" apply uniformly (no specific target to name).
const DIMENSIONS_WITHOUT_TARGET = new Set<PersonalPolicyLimitDimension>(['line', 'declared_valuation'])

const EMPTY_DRAFT: PersonalPolicyDraft = {
  objective_growth: false,
  objective_income: false,
  objective_preservation: false,
  objective_note: null,
  horizon: null,
  horizon_target_date: null,
  liquidity_need_amount: null,
  liquidity_need_date: null,
  liquidity_note: null,
  risk_tolerance_note: null,
  loss_capacity_pct: null,
}

function toDraft(policy: PersonalPolicy): PersonalPolicyDraft {
  const { updated_at: _updated_at, ...draft } = policy
  return draft
}

function isPolicyEmpty(policy: PersonalPolicy): boolean {
  return (
    !policy.objective_growth &&
    !policy.objective_income &&
    !policy.objective_preservation &&
    !policy.objective_note &&
    !policy.horizon &&
    !policy.horizon_target_date &&
    policy.liquidity_need_amount === null &&
    !policy.liquidity_note &&
    !policy.risk_tolerance_note &&
    policy.loss_capacity_pct === null
  )
}

function rangeLabel(minPct: number | null, maxPct: number | null, formatNumber: (v: number) => string): string {
  if (minPct !== null && maxPct !== null) return `${formatNumber(minPct)}–${formatNumber(maxPct)}%`
  if (maxPct !== null) return `≤ ${formatNumber(maxPct)}%`
  if (minPct !== null) return `≥ ${formatNumber(minPct)}%`
  return '—'
}

/**
 * The user's own, self-declared investment policy — objective, horizon,
 * liquidity need, risk tolerance, and personal concentration limits.
 * Purely descriptive throughout: comparisons against the current
 * portfolio ("gaps") are stated as facts, never as a suggestion to buy or
 * sell anything, matching the score/allocation posture used everywhere
 * else in this app. Placed on the Portfolio page, next to allocation and
 * breakdown — this is portfolio strategy, not a data-administration
 * setting. See DEVLOG "Decision 3u.59".
 */
export function PersonalPolicyPanel() {
  const { t, formatNumber, formatDate } = useI18n()
  const [policy, setPolicy] = useState<PersonalPolicy | null>(null)
  const [limits, setLimits] = useState<PersonalPolicyLimit[] | null>(null)
  const [gaps, setGaps] = useState<PersonalPolicyGap[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<PersonalPolicyDraft>(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const [limitDimension, setLimitDimension] = useState<PersonalPolicyLimitDimension>('line')
  const [limitTarget, setLimitTarget] = useState('')
  const [limitMin, setLimitMin] = useState('')
  const [limitMax, setLimitMax] = useState('')
  const [limitBusy, setLimitBusy] = useState(false)
  const [limitError, setLimitError] = useState<string | null>(null)

  function loadAll() {
    setError(null)
    Promise.all([api.getPersonalPolicy(), api.getPersonalPolicyLimits(), api.getPersonalPolicyGaps()])
      .then(([p, l, g]) => {
        setPolicy(p)
        setLimits(l)
        setGaps(g)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(loadAll, [])

  function startEdit() {
    if (policy) setDraft(toDraft(policy))
    setSaveError(null)
    setEditing(true)
  }

  async function saveDraft() {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await api.setPersonalPolicy(draft)
      setPolicy(updated)
      setEditing(false)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  async function addLimit() {
    const min = limitMin.trim() === '' ? null : Number(limitMin.trim().replace(',', '.'))
    const max = limitMax.trim() === '' ? null : Number(limitMax.trim().replace(',', '.'))
    setLimitBusy(true)
    setLimitError(null)
    try {
      await api.createPersonalPolicyLimit({
        dimension: limitDimension,
        target: DIMENSIONS_WITHOUT_TARGET.has(limitDimension) ? null : limitTarget.trim(),
        min_pct: min !== null && Number.isFinite(min) ? min : null,
        max_pct: max !== null && Number.isFinite(max) ? max : null,
      })
      setLimitTarget('')
      setLimitMin('')
      setLimitMax('')
      loadAll()
    } catch (err) {
      setLimitError(err instanceof Error ? err.message : String(err))
    } finally {
      setLimitBusy(false)
    }
  }

  async function removeLimit(id: number) {
    try {
      await api.deletePersonalPolicyLimit(id)
      loadAll()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  if (error) return <div className="card notice error">{error}</div>
  if (policy === null || limits === null || gaps === null) return null

  const objectiveLabels = [
    policy.objective_growth ? t('policy.objective.growth') : null,
    policy.objective_income ? t('policy.objective.income') : null,
    policy.objective_preservation ? t('policy.objective.preservation') : null,
  ].filter((label): label is string => label !== null)

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
        <div>
          <h2>{t('policy.title')}</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            {t('policy.subtitle')}
          </p>
        </div>
        {!editing && <button onClick={startEdit}>{t('policy.edit')}</button>}
      </div>

      {editing ? (
        <div>
          <div className="form-row">
            <div className="field">
              <label>
                <input
                  type="checkbox"
                  checked={draft.objective_growth}
                  onChange={(e) => setDraft({ ...draft, objective_growth: e.target.checked })}
                />{' '}
                {t('policy.objective.growth')}
              </label>
            </div>
            <div className="field">
              <label>
                <input
                  type="checkbox"
                  checked={draft.objective_income}
                  onChange={(e) => setDraft({ ...draft, objective_income: e.target.checked })}
                />{' '}
                {t('policy.objective.income')}
              </label>
            </div>
            <div className="field">
              <label>
                <input
                  type="checkbox"
                  checked={draft.objective_preservation}
                  onChange={(e) => setDraft({ ...draft, objective_preservation: e.target.checked })}
                />{' '}
                {t('policy.objective.preservation')}
              </label>
            </div>
          </div>
          <div className="form-row">
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="policy-objective-note">{t('policy.objectiveNote')}</label>
              <input
                id="policy-objective-note"
                value={draft.objective_note ?? ''}
                onChange={(e) => setDraft({ ...draft, objective_note: e.target.value || null })}
              />
            </div>
          </div>

          <div className="form-row">
            <div className="field">
              <label htmlFor="policy-horizon">{t('policy.horizon')}</label>
              <select
                id="policy-horizon"
                value={draft.horizon ?? ''}
                onChange={(e) => setDraft({ ...draft, horizon: (e.target.value || null) as PersonalPolicyDraft['horizon'] })}
              >
                <option value="">—</option>
                <option value="short">{t('policy.horizon.short')}</option>
                <option value="medium">{t('policy.horizon.medium')}</option>
                <option value="long">{t('policy.horizon.long')}</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="policy-horizon-date">{t('policy.horizonTargetDate')}</label>
              <input
                id="policy-horizon-date"
                type="date"
                value={draft.horizon_target_date ?? ''}
                onChange={(e) => setDraft({ ...draft, horizon_target_date: e.target.value || null })}
              />
            </div>
          </div>

          <div className="form-row">
            <div className="field">
              <label htmlFor="policy-liquidity-amount">{t('policy.liquidityAmount')}</label>
              <input
                id="policy-liquidity-amount"
                value={draft.liquidity_need_amount ?? ''}
                placeholder="5000"
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    liquidity_need_amount: e.target.value.trim() === '' ? null : Number(e.target.value.replace(',', '.')),
                  })
                }
              />
            </div>
            <div className="field">
              <label htmlFor="policy-liquidity-date">{t('policy.liquidityDate')}</label>
              <input
                id="policy-liquidity-date"
                type="date"
                value={draft.liquidity_need_date ?? ''}
                onChange={(e) => setDraft({ ...draft, liquidity_need_date: e.target.value || null })}
              />
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="policy-liquidity-note">{t('policy.liquidityNote')}</label>
              <input
                id="policy-liquidity-note"
                value={draft.liquidity_note ?? ''}
                onChange={(e) => setDraft({ ...draft, liquidity_note: e.target.value || null })}
              />
            </div>
          </div>

          <div className="form-row">
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="policy-risk-note">{t('policy.riskToleranceNote')}</label>
              <input
                id="policy-risk-note"
                value={draft.risk_tolerance_note ?? ''}
                onChange={(e) => setDraft({ ...draft, risk_tolerance_note: e.target.value || null })}
              />
            </div>
            <div className="field">
              <label htmlFor="policy-loss-capacity">{t('policy.lossCapacityPct')}</label>
              <input
                id="policy-loss-capacity"
                value={draft.loss_capacity_pct ?? ''}
                placeholder="30"
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    loss_capacity_pct: e.target.value.trim() === '' ? null : Number(e.target.value.replace(',', '.')),
                  })
                }
              />
            </div>
          </div>

          {saveError && <div className="notice error">{saveError}</div>}
          <button className="primary" disabled={saving} onClick={() => void saveDraft()}>
            {saving ? t('common.saving') : t('common.save')}
          </button>{' '}
          <button className="link" disabled={saving} onClick={() => setEditing(false)}>
            {t('common.cancel')}
          </button>
        </div>
      ) : isPolicyEmpty(policy) ? (
        <p className="muted" style={{ marginTop: 0 }}>
          {t('policy.empty')}
        </p>
      ) : (
        <dl className="position-detail-facts">
          <div>
            <dt>{t('policy.objective')}</dt>
            <dd>
              {objectiveLabels.length > 0 ? objectiveLabels.join(', ') : '—'}
              {policy.objective_note ? ` — ${policy.objective_note}` : ''}
            </dd>
          </div>
          <div>
            <dt>{t('policy.horizon')}</dt>
            <dd>
              {policy.horizon ? t(`policy.horizon.${policy.horizon}`) : '—'}
              {policy.horizon_target_date ? ` (${formatDate(policy.horizon_target_date)})` : ''}
            </dd>
          </div>
          <div>
            <dt>{t('policy.liquidity')}</dt>
            <dd>
              {policy.liquidity_need_amount !== null ? formatNumber(policy.liquidity_need_amount) : '—'}
              {policy.liquidity_need_date ? ` — ${formatDate(policy.liquidity_need_date)}` : ''}
              {policy.liquidity_note ? ` (${policy.liquidity_note})` : ''}
            </dd>
          </div>
          <div>
            <dt>{t('policy.riskTolerance')}</dt>
            <dd>
              {policy.risk_tolerance_note ?? '—'}
              {policy.loss_capacity_pct !== null ? ` — ${t('policy.lossCapacityValue', { pct: formatNumber(policy.loss_capacity_pct) })}` : ''}
            </dd>
          </div>
        </dl>
      )}

      <h3 style={{ marginTop: '1.2rem' }}>{t('policy.limits.title')}</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        {t('policy.limits.subtitle')}
      </p>

      {limits.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('policy.limits.dimension')}</th>
                <th>{t('policy.limits.target')}</th>
                <th className="num">{t('policy.limits.range')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {limits.map((limit) => (
                <tr key={limit.id}>
                  <td>{t(`policy.dimension.${limit.dimension}`)}</td>
                  <td>{limit.target ?? '—'}</td>
                  <td className="num">{rangeLabel(limit.min_pct, limit.max_pct, (v) => formatNumber(v, 1))}</td>
                  <td>
                    <button className="link" onClick={() => void removeLimit(limit.id)}>
                      {t('common.delete')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="form-row" style={{ marginTop: '0.6rem' }}>
        <div className="field">
          <label htmlFor="policy-limit-dimension">{t('policy.limits.dimension')}</label>
          <select
            id="policy-limit-dimension"
            value={limitDimension}
            onChange={(e) => setLimitDimension(e.target.value as PersonalPolicyLimitDimension)}
          >
            {LIMIT_DIMENSIONS.map((dim) => (
              <option key={dim} value={dim}>
                {t(`policy.dimension.${dim}`)}
              </option>
            ))}
          </select>
        </div>
        {!DIMENSIONS_WITHOUT_TARGET.has(limitDimension) && (
          <div className="field">
            <label htmlFor="policy-limit-target">{t('policy.limits.target')}</label>
            <input
              id="policy-limit-target"
              value={limitTarget}
              placeholder={t(`policy.limits.targetPlaceholder.${limitDimension}`)}
              onChange={(e) => setLimitTarget(e.target.value)}
            />
          </div>
        )}
        <div className="field">
          <label htmlFor="policy-limit-min">{t('policy.limits.min')}</label>
          <input
            id="policy-limit-min"
            style={{ width: '4rem' }}
            value={limitMin}
            placeholder="0"
            onChange={(e) => setLimitMin(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="policy-limit-max">{t('policy.limits.max')}</label>
          <input
            id="policy-limit-max"
            style={{ width: '4rem' }}
            value={limitMax}
            placeholder="10"
            onChange={(e) => setLimitMax(e.target.value)}
          />
        </div>
        <button
          disabled={limitBusy || (!DIMENSIONS_WITHOUT_TARGET.has(limitDimension) && limitTarget.trim() === '')}
          onClick={() => void addLimit()}
        >
          {limitBusy ? t('common.saving') : t('common.add')}
        </button>
      </div>
      {limitError && <div className="notice error">{limitError}</div>}

      {limits.length > 0 && (
        <div style={{ marginTop: '0.9rem' }}>
          {gaps.length === 0 ? (
            <p className="muted" style={{ marginTop: 0 }}>
              {t('policy.gaps.allWithin')}
            </p>
          ) : (
            <>
              <p className="muted" style={{ marginTop: 0 }}>
                {t('policy.gaps.disclaimer')}
              </p>
              <ul className="attention-list">
                {gaps.map((gap) => (
                  <li key={`${gap.limit_id}-${gap.target ?? ''}`} className="attention-item warning">
                    {t(`policy.dimension.${gap.dimension}`)}
                    {gap.target ? ` — ${gap.target}` : ''}
                    {': '}
                    {formatNumber(gap.current_pct, 1)}% (
                    <span className={`tag ${gap.state === 'over' ? 'unresolved' : 'neutral'}`}>
                      {t(`allocation.state.${gap.state}`)}
                    </span>{' '}
                    {t('policy.gaps.yourLimit', { range: rangeLabel(gap.min_pct, gap.max_pct, (v) => formatNumber(v, 1)) })})
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}
