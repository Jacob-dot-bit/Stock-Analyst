import { useState } from 'react'
import { api } from '../api/client'
import type { BacktestReport } from '../api/types'
import { useI18n } from '../i18n'

/**
 * Phase 2 of a real, backtestable Discovery prediction: an honest,
 * unrounded report of a walk-forward-validated logistic regression over
 * the price-only feature set (`prediction/features.py`). Deliberately an
 * aggregate report of the model's own historical performance — never a
 * per-instrument "predicted up/down" label, which this app's real result
 * (barely-above-chance accuracy, one test period) does not support
 * showing responsibly. See DEVLOG "Decision 3u.23"/"Decision 3u.66".
 */
export function BacktestPanel() {
  const { t, formatNumber } = useI18n()
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<BacktestReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      setReport(await api.runBacktest())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h3 style={{ marginBottom: '0.2rem' }}>{t('backtest.title')}</h3>
      <p className="muted" style={{ marginTop: 0, fontSize: '0.85rem' }}>
        {t('backtest.description')}
      </p>
      <div className="form-row">
        <button disabled={busy} onClick={() => void run()}>
          {busy ? t('backtest.running') : t('backtest.run')}
        </button>
      </div>

      {error && (
        <div className="notice error" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
          {error}
        </div>
      )}

      {report && (
        <div style={{ marginTop: '0.8rem' }}>
          <div className="notice warning" style={{ marginBottom: '0.8rem' }}>
            {t('backtest.disclaimer')}
          </div>

          <dl className="position-detail-facts">
            <div>
              <dt>{t('backtest.instrumentsUsed')}</dt>
              <dd>{formatNumber(report.instruments_used, 0)}</dd>
            </div>
            <div>
              <dt>{t('backtest.trainPeriod')}</dt>
              <dd>
                {report.train_start && report.train_end
                  ? `${report.train_start} → ${report.train_end}`
                  : '—'}{' '}
                ({formatNumber(report.train_samples, 0)})
              </dd>
            </div>
            <div>
              <dt>{t('backtest.testPeriod')}</dt>
              <dd>
                {report.test_start && report.test_end ? `${report.test_start} → ${report.test_end}` : '—'}{' '}
                ({formatNumber(report.test_samples, 0)})
              </dd>
            </div>
          </dl>

          {report.single_class_warning && (
            <div className="notice warning" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
              {t('backtest.singleClassWarning')}
            </div>
          )}

          {!report.single_class_warning && report.test_accuracy !== null && (
            <dl className="position-detail-facts" style={{ marginTop: '0.6rem' }}>
              <div>
                <dt>{t('backtest.testAccuracy')}</dt>
                <dd>{formatNumber(report.test_accuracy * 100)}%</dd>
              </div>
              <div>
                <dt>{t('backtest.avgReturnUp')}</dt>
                <dd>{report.avg_return_predicted_up !== null ? `${formatNumber(report.avg_return_predicted_up * 100, 2)}%` : '—'}</dd>
              </div>
              <div>
                <dt>{t('backtest.avgReturnDown')}</dt>
                <dd>{report.avg_return_predicted_down !== null ? `${formatNumber(report.avg_return_predicted_down * 100, 2)}%` : '—'}</dd>
              </div>
            </dl>
          )}

          {report.low_sample_warning && (
            <div className="notice warning" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
              {t('backtest.lowSampleWarning')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
