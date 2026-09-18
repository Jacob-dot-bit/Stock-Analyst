import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { FactorLoadings } from '../api/types'
import { useI18n } from '../i18n'

/**
 * Carhart four-factor exposure for held positions — explanatory only
 * (what has historically driven a holding's returns), never predictive:
 * a factor loading states a fact about the past, it forecasts nothing.
 * Held positions only, daily returns, region-matched (a US instrument
 * against Kenneth French's US factor series, a European one against
 * Europe's — never mixed). See DEVLOG "Decision 3u.24". Self-contained,
 * same pattern as `AllocationTargets`/`PortfolioBreakdown` (own fetch, no
 * props from the page).
 */
export function FactorExposures() {
  const { t, formatNumber } = useI18n()
  const [rows, setRows] = useState<FactorLoadings[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [importNotice, setImportNotice] = useState<string | null>(null)

  function load() {
    setError(null)
    api
      .getFactorLoadings()
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  useEffect(load, [])

  async function handleImport() {
    setImporting(true)
    setError(null)
    try {
      const result = await api.importFactorData()
      setImportNotice(t('factors.importResult', { imported: result.imported, alreadyPresent: result.already_present }))
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setImporting(false)
    }
  }

  function pct(value: number | null): string {
    return value === null ? '—' : formatNumber(value * 100, 1) + ' %'
  }

  function beta(value: number | null): string {
    return value === null ? '—' : formatNumber(value, 2)
  }

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
        <div>
          <h2 className="compact">{t('factors.title')}</h2>
          <span className="muted">{t('factors.description')}</span>
        </div>
        <button disabled={importing} onClick={() => void handleImport()}>
          {importing ? t('common.saving') : t('factors.import')}
        </button>
      </div>

      {importNotice && (
        <div className="muted" style={{ fontSize: '0.82rem', marginTop: '0.5rem' }}>
          {importNotice}
        </div>
      )}

      {error && (
        <div className="notice error" style={{ marginTop: '1rem', marginBottom: 0 }}>
          {error}
        </div>
      )}

      {rows && rows.length === 0 && <div className="empty">{t('factors.empty')}</div>}

      {rows && rows.length > 0 && (
        <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
          <table>
            <thead>
              <tr>
                <th>{t('table.instrument')}</th>
                <th>{t('factors.region')}</th>
                <th className="num" title={t('factors.alphaTooltip')}>
                  {t('factors.alpha')}
                </th>
                <th className="num" title={t('factors.betaMktTooltip')}>
                  {t('factors.betaMkt')}
                </th>
                <th className="num" title={t('factors.betaSmbTooltip')}>
                  {t('factors.betaSmb')}
                </th>
                <th className="num" title={t('factors.betaHmlTooltip')}>
                  {t('factors.betaHml')}
                </th>
                <th className="num" title={t('factors.betaMomTooltip')}>
                  {t('factors.betaMom')}
                </th>
                <th className="num" title={t('factors.rSquaredTooltip')}>
                  {t('factors.rSquared')}
                </th>
                <th className="num">{t('factors.observations')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.instrument.id}>
                  <td>
                    <strong>{row.instrument.broker_symbol}</strong>
                    {row.instrument.name && (
                      <div className="muted" style={{ fontSize: '0.78rem' }}>
                        {row.instrument.name}
                      </div>
                    )}
                  </td>
                  {row.not_applicable_reason ? (
                    <td colSpan={8} className="muted">
                      {t(`factors.notApplicable.${row.not_applicable_reason}`)}
                    </td>
                  ) : (
                    <>
                      <td>{row.region}</td>
                      <td className="num">{pct(row.alpha)}</td>
                      <td className="num">{beta(row.beta_mkt)}</td>
                      <td className="num">{beta(row.beta_smb)}</td>
                      <td className="num">{beta(row.beta_hml)}</td>
                      <td className="num">{beta(row.beta_mom)}</td>
                      <td className="num">{row.r_squared !== null ? formatNumber(row.r_squared, 2) : '—'}</td>
                      <td className="num">{row.n_observations}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
