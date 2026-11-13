import { api } from '../api/client'
import { useI18n } from '../i18n'
import { FundamentalsRefreshButton } from './FundamentalsRefreshButton'
import { MaintenanceAction } from './MaintenanceAction'
import { PredictionBackfillButton } from './PredictionBackfillButton'

/**
 * Every catch-up action in one place (DEVLOG "Step 3u.99"). They used to sit
 * on six different pages — the ISIN and FIGI lookups twice — next to views
 * that only need their result. Daily price refreshes stay on the Portfolio
 * page: that one is part of reading the portfolio, not maintenance.
 */
export function DataMaintenancePanel() {
  const { t } = useI18n()

  return (
    <>
      <FundamentalsRefreshButton onRefreshed={() => {}} />

      <div className="card">
        <h2>{t('maintenance.identity.title')}</h2>
        <MaintenanceAction
          title={t('duplicates.backfillIsins')}
          description={t('maintenance.isins.description')}
          label={t('maintenance.run')}
          run={async () => {
            const result = await api.backfillIsins()
            return t('duplicates.backfillResult', { checked: result.checked, updated: result.updated })
          }}
        />
        <MaintenanceAction
          title={t('duplicates.backfillFigis')}
          description={t('maintenance.figis.description')}
          label={t('maintenance.run')}
          run={async () => {
            const result = await api.backfillFigis()
            return result.remaining > 0
              ? t('duplicates.backfillFigisResultMore', { checked: result.checked, remaining: result.remaining })
              : t('duplicates.backfillFigisResultDone', { checked: result.checked })
          }}
        />
        <MaintenanceAction
          title={t('breakdown.enrichSectors')}
          description={t('maintenance.sectors.description')}
          label={t('maintenance.run')}
          run={async () => {
            const result = await api.enrichSectors()
            return t('breakdown.enrichResult', {
              enriched: result.enriched,
              skipped: result.skipped,
              failed: result.failed,
            })
          }}
        />
      </div>

      <div className="card">
        <h2>{t('maintenance.analysis.title')}</h2>
        <MaintenanceAction
          title={t('factors.import')}
          description={t('maintenance.factors.description')}
          label={t('maintenance.run')}
          run={async () => {
            const result = await api.importFactorData()
            return t('factors.importResult', { imported: result.imported, alreadyPresent: result.already_present })
          }}
        />
        <MaintenanceAction
          title={t('discovery.backfillDividends')}
          description={t('maintenance.dividends.description')}
          label={t('maintenance.run')}
          run={async () => {
            const result = await api.backfillDiscoveryDividends()
            return result.remaining > 0
              ? t('discovery.refreshResultMore', { evaluated: result.evaluated, remaining: result.remaining })
              : t('discovery.refreshResultDone', { evaluated: result.evaluated })
          }}
        />
        <div className="maintenance-action">
          <PredictionBackfillButton />
        </div>
      </div>
    </>
  )
}
