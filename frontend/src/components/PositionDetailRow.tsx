import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { AllocationRow, CorporateAction, DividendDetailRow, Lot, Position, PositionSignal, Score, Transaction } from '../api/types'
import { signClass } from '../format'
import { useI18n } from '../i18n'
import { InsightsSection } from './InsightsDetailRow'
import { ScoreBreakdown } from './ScoreDetailRow'

function categoryLabel(category: string | null, t: (key: string) => string): string {
  if (!category) return t('breakdown.unknown')
  const key = `breakdown.category.${category}`
  const translated = t(key)
  return translated === key ? category : translated
}

/** Never render the raw backend reason code (e.g. "corporate_action")
 * directly — every value gets a translated sentence, and an unmapped
 * future value still degrades to a translated fallback rather than a raw
 * snake_case string. See DEVLOG "Decision 3u.38". */
function notPriceableReasonLabel(reason: string, t: (key: string) => string): string {
  const key = `positionDetail.notPriceableReasonValue.${reason}`
  const translated = t(key)
  return translated === key ? t('positionDetail.notPriceableReasonValue.unknown') : translated
}

interface FetchedData {
  lots: Lot[]
  dividends: DividendDetailRow[]
  corporateActions: CorporateAction[]
  transactions: Transaction[]
  allocation: AllocationRow[]
}

/**
 * The consolidated per-position detail panel — one "Détails" affordance
 * replaces the separate Score/Insights expand buttons that used to live in
 * this table specifically (Watchlist/Screener keep those, unchanged — see
 * `ScoreDetailRow.tsx`/`InsightsDetailRow.tsx`). Sections are plain
 * vertical blocks, not tabs or an accordion, so nothing is hidden behind
 * secondary navigation. No price chart in v1 — deliberately deferred, see
 * DEVLOG "Decision 3u.31".
 */
export function PositionDetailRow({
  position,
  score,
  signal,
  baseCurrency,
  colSpan,
}: {
  position: Position
  score: Score | undefined
  signal: PositionSignal | undefined
  baseCurrency: string
  colSpan: number
}) {
  const { t, formatNumber, formatSignedPercent, formatDate } = useI18n()
  const [data, setData] = useState<FetchedData | 'loading' | null>('loading')
  const fetchedForRef = useRef<number | null>(null)
  const instrumentId = position.instrument.id

  useEffect(() => {
    if (fetchedForRef.current === instrumentId) return
    fetchedForRef.current = instrumentId

    setData('loading')
    Promise.all([
      api.getLots(instrumentId),
      api.getDividendDetail({ instrumentId }),
      api.getCorporateActions({ instrumentId }),
      api.getTransactions({ instrumentId }),
      api.getAllocation(),
    ])
      .then(([lots, dividends, corporateActions, transactionList, allocation]) => {
        if (fetchedForRef.current !== instrumentId) return
        setData({ lots, dividends, corporateActions, transactions: transactionList.transactions, allocation })
      })
      .catch(() => {
        if (fetchedForRef.current === instrumentId) setData(null)
      })
  }, [instrumentId])

  const openLots = data && data !== 'loading' ? data.lots.filter((l) => l.lot_type === 'OPEN') : []
  const closedLots = data && data !== 'loading' ? data.lots.filter((l) => l.lot_type === 'CLOSED') : []
  const categoryRow =
    data && data !== 'loading' && position.instrument.category
      ? data.allocation.find((row) => row.category === position.instrument.category)
      : undefined
  const categoryShare =
    categoryRow && categoryRow.current_value > 0 && position.current_value !== null
      ? (position.current_value / categoryRow.current_value) * 100
      : null

  return (
    <tr className="position-detail-row">
      <td colSpan={colSpan}>
        <div className="position-detail">
          <section className="position-detail-section">
            <h4>{t('positionDetail.summary')}</h4>
            <dl className="position-detail-facts">
              <div>
                <dt>{t('table.quantity')}</dt>
                <dd>{formatNumber(position.quantity, 4)}</dd>
              </div>
              <div>
                <dt>{t('table.avgPrice')}</dt>
                <dd
                  title={
                    position.instrument.category === 'P2P'
                      ? t('table.avgPriceNotApplicableTooltip', {
                          date: position.opened_at ? formatDate(position.opened_at) : '—',
                        })
                      : undefined
                  }
                >
                  {position.instrument.category === 'P2P' ? (
                    t('common.notApplicable')
                  ) : (
                    <>
                      {formatNumber(position.avg_price)}
                      {position.currency ? ` ${position.currency}` : ''}
                    </>
                  )}
                </dd>
              </div>
              <div>
                <dt>{t('table.price')}</dt>
                <dd>{formatNumber(position.current_price ?? position.market_price)}</dd>
              </div>
              <div>
                <dt>{t('table.value', { currency: baseCurrency })}</dt>
                <dd>{position.current_value !== null ? formatNumber(position.current_value) : '—'}</dd>
              </div>
              <div>
                <dt>{t('table.unrealized', { currency: baseCurrency })}</dt>
                <dd className={signClass(position.current_unrealized_pl)}>
                  {position.current_unrealized_pl !== null ? formatNumber(position.current_unrealized_pl) : '—'}
                  {position.current_unrealized_pl_pct !== null
                    ? ` (${formatSignedPercent(position.current_unrealized_pl_pct)})`
                    : ''}
                </dd>
              </div>
              <div>
                <dt>{t('table.weight')}</dt>
                <dd>{position.weight_percent !== null ? `${formatNumber(position.weight_percent, 1)}%` : '—'}</dd>
              </div>
              <div>
                <dt>{t('table.account')}</dt>
                <dd>{position.account ?? '—'}</dd>
              </div>
              <div>
                <dt>{t('table.since')}</dt>
                <dd>{formatDate(position.opened_at)}</dd>
              </div>
            </dl>
          </section>

          <section className="position-detail-section">
            <h4>{t('positionDetail.allocation')}</h4>
            {signal ? (
              <dl className="position-detail-facts">
                <div>
                  <dt>{t('allocation.category')}</dt>
                  <dd>{categoryLabel(signal.category, t)}</dd>
                </div>
                <div>
                  <dt title={t('allocation.gapTooltip')}>{t('allocation.gap')}</dt>
                  <dd>
                    {t(`allocation.state.${signal.allocation_state}`)}
                    {(signal.allocation_state === 'under' || signal.allocation_state === 'over') &&
                      ` (${formatNumber(signal.gap_pct, 1)} pts)`}
                  </dd>
                </div>
                {categoryRow && (
                  <div>
                    <dt>{t('allocation.target')}</dt>
                    <dd>
                      {categoryRow.min_pct !== null && categoryRow.max_pct !== null
                        ? `${formatNumber(categoryRow.min_pct, 1)}–${formatNumber(categoryRow.max_pct, 1)}%`
                        : '—'}
                    </dd>
                  </div>
                )}
                {categoryShare !== null && (
                  <div>
                    <dt>{t('positionDetail.categoryShare')}</dt>
                    <dd>{formatNumber(categoryShare, 1)}%</dd>
                  </div>
                )}
              </dl>
            ) : (
              <p className="muted">{t('positionDetail.noAllocationData')}</p>
            )}
          </section>

          <section className="position-detail-section">
            <h4>{t('positionDetail.analysis')}</h4>
            {score && score.composite !== null ? (
              <ScoreBreakdown score={score} />
            ) : (
              <p className="muted">{t('positionDetail.noScoreData')}</p>
            )}
            <InsightsSection instrumentId={instrumentId} />
          </section>

          <section className="position-detail-section">
            <h4>{t('positionDetail.income')}</h4>
            {data === 'loading' && <p className="muted">{t('common.loading')}</p>}
            {data === null && <p className="muted">{t('positionDetail.loadError')}</p>}
            {data && data !== 'loading' && data.dividends.length === 0 && (
              <p className="muted">{t('dividends.detailEmpty')}</p>
            )}
            {data && data !== 'loading' && data.dividends.length > 0 && (
              <>
                <div className="notice info" style={{ marginBottom: '0.6rem' }}>
                  {t('dividends.disclaimer')}
                </div>
                <table className="position-detail-table">
                <thead>
                  <tr>
                    <th>{t('dividends.date')}</th>
                    <th className="num">{t('dividends.gross')}</th>
                    <th className="num">{t('dividends.withholding')}</th>
                    <th className="num">{t('dividends.net')}</th>
                    <th>{t('dividends.reconciliation')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.dividends.map((row) => (
                    <tr key={row.id}>
                      <td>{formatDate(row.executed_at)}</td>
                      <td className="num">{row.gross !== null ? formatNumber(row.gross) : '—'}</td>
                      <td className={`num ${row.withholding_tax !== null ? signClass(row.withholding_tax) : ''}`}>
                        {row.withholding_tax !== null ? formatNumber(row.withholding_tax) : '—'}
                      </td>
                      <td className="num">{row.net !== null ? formatNumber(row.net) : '—'}</td>
                      <td>{t(`dividends.status.${row.reconciliation_status}`)}</td>
                    </tr>
                  ))}
                </tbody>
                </table>
              </>
            )}
          </section>

          <section className="position-detail-section">
            <h4>{t('positionDetail.history')}</h4>
            {data === 'loading' && <p className="muted">{t('common.loading')}</p>}
            {data && data !== 'loading' && (
              <>
                <h5>{t('positionDetail.openLots')}</h5>
                {openLots.length === 0 ? (
                  <p className="muted">{t('positionDetail.noLots')}</p>
                ) : (
                  <table className="position-detail-table">
                    <thead>
                      <tr>
                        <th>{t('positionDetail.lotOpenedAt')}</th>
                        <th className="num">{t('table.quantity')}</th>
                        <th className="num">{t('table.avgPrice')}</th>
                        <th>{t('table.account')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {openLots.map((lot) => (
                        <tr key={lot.id}>
                          <td>{formatDate(lot.opened_at)}</td>
                          <td className="num">{formatNumber(lot.quantity, 4)}</td>
                          <td className="num">
                            {formatNumber(lot.open_price)}
                            {lot.currency ? ` ${lot.currency}` : ''}
                          </td>
                          <td>{lot.account ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {closedLots.length > 0 && (
                  <>
                    <h5>{t('positionDetail.closedLots')}</h5>
                    <table className="position-detail-table">
                      <thead>
                        <tr>
                          <th>{t('positionDetail.lotOpenedAt')}</th>
                          <th>{t('positionDetail.lotClosedAt')}</th>
                          <th className="num">{t('table.quantity')}</th>
                          <th className="num">{t('table.avgPrice')}</th>
                          <th className="num">{t('positionDetail.closePrice')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {closedLots.map((lot) => (
                          <tr key={lot.id}>
                            <td>{formatDate(lot.opened_at)}</td>
                            <td>{formatDate(lot.closed_at)}</td>
                            <td className="num">{formatNumber(lot.quantity, 4)}</td>
                            <td className="num">{formatNumber(lot.open_price)}</td>
                            <td className="num">{lot.close_price !== null ? formatNumber(lot.close_price) : '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}

                {data.corporateActions.length > 0 && (
                  <>
                    <h5>{t('corporateActions.title')}</h5>
                    <table className="position-detail-table">
                      <thead>
                        <tr>
                          <th>{t('corporateActions.date')}</th>
                          <th>{t('corporateActions.type')}</th>
                          <th className="num">{t('corporateActions.ratio')}</th>
                          <th>{t('corporateActions.source')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.corporateActions.map((action) => (
                          <tr key={action.id}>
                            <td>{formatDate(action.effective_date)}</td>
                            <td>{t(`corporateActions.type.${action.action_type}`)}</td>
                            <td className="num">
                              {action.ratio_numerator}:{action.ratio_denominator}
                            </td>
                            <td>{t(`corporateActions.source.${action.source}`)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}

                <h5>{t('positionDetail.relatedTransactions')}</h5>
                {data.transactions.length === 0 ? (
                  <p className="muted">{t('positionDetail.noTransactions')}</p>
                ) : (
                  <table className="position-detail-table">
                    <thead>
                      <tr>
                        <th>{t('table.since')}</th>
                        <th>{t('transactions.type')}</th>
                        <th className="num">{t('table.value', { currency: baseCurrency })}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.transactions.map((tx) => (
                        <tr key={tx.id}>
                          <td>{formatDate(tx.executed_at)}</td>
                          <td>{t(`transactions.type.${tx.type}`)}</td>
                          <td className="num">{tx.amount !== null ? formatNumber(tx.amount) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )}
          </section>

          <section className="position-detail-section">
            <h4>{t('positionDetail.dataQuality')}</h4>
            <dl className="position-detail-facts">
              <div>
                <dt>{t('positionDetail.priceStatus')}</dt>
                <dd>
                  {position.instrument.price_status ? t(`priceStatus.${position.instrument.price_status}`) : '—'}
                </dd>
              </div>
              <div>
                <dt>{t('positionDetail.verifiedProvider')}</dt>
                <dd>
                  {position.instrument.verified_provider
                    ? `${position.instrument.verified_provider} — ${formatDate(position.instrument.verified_at)}`
                    : '—'}
                </dd>
              </div>
              <div>
                <dt>{t('positionDetail.mappingStatus')}</dt>
                <dd>{t(`positionDetail.mappingStatusValue.${position.instrument.mapping_status}`)}</dd>
              </div>
              {position.instrument.not_priceable_reason && (
                <div>
                  <dt>{t('positionDetail.notPriceableReason')}</dt>
                  <dd>{notPriceableReasonLabel(position.instrument.not_priceable_reason, t)}</dd>
                </div>
              )}
            </dl>
          </section>
        </div>
      </td>
    </tr>
  )
}
