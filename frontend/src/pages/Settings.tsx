import { useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../api/client'
import type { Instrument, ProviderAvailability } from '../api/types'
import { BackupPanel } from '../components/BackupPanel'
import { CorporateActionsPanel } from '../components/CorporateActionsPanel'
import { DataHealthPanel } from '../components/DataHealthPanel'
import { FundamentalsRefreshButton } from '../components/FundamentalsRefreshButton'
import { ImportPanel } from '../components/ImportPanel'
import { ManualPositionForm } from '../components/ManualPositionForm'
import { UnresolvedPanel } from '../components/UnresolvedPanel'
import { useI18n } from '../i18n'

interface ProviderStatus {
  name: string
  enabled: boolean
  description?: string
  signup_url?: string | null
  has_api_key: boolean
}

interface Notice {
  type: 'success' | 'error'
  message: string
}

type TestResult = 'testing' | { valid: boolean; message: string }

export default function Settings() {
  const { t } = useI18n()
  const location = useLocation()
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [availability, setAvailability] = useState<ProviderAvailability[]>([])
  const [apiKeysStatus, setApiKeysStatus] = useState<Record<string, boolean>>({})
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({})
  const [unresolvedInstruments, setUnresolvedInstruments] = useState<Instrument[]>([])

  const loadUnresolved = useCallback(async () => {
    const portfolio = await api.getPortfolio()
    setUnresolvedInstruments(portfolio.unresolved_symbols)
  }, [])

  // Load provider status and current API keys on mount
  useEffect(() => {
    const loadSettings = async () => {
      try {
        setLoading(true)
        const [providerList, keysStatus, availabilityList] = await Promise.all([
          api.getProviderStatus(),
          api.getApiKeysStatus(),
          api.getProviderAvailability(),
          loadUnresolved(),
        ])
        setProviders(providerList)
        setApiKeysStatus(keysStatus)
        setAvailability(availabilityList)
      } catch (err) {
        setNotice({
          type: 'error',
          message: String(err),
        })
      } finally {
        setLoading(false)
      }
    }

    loadSettings()
  }, [loadUnresolved])

  // No existing precedent for hash-anchor scrolling in this codebase — added
  // here so links like "Gérer les données" (Portfolio.tsx) and the
  // unresolved-instruments item (AttentionCard.tsx) land on the right group
  // instead of just the top of a page that keeps growing longer.
  useEffect(() => {
    if (!location.hash) return
    const target = document.getElementById(location.hash.slice(1))
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [location.hash, loading])

  const handleSave = useCallback(async () => {
    setBusy(true)
    setNotice(null)

    try {
      const payload = Object.fromEntries(
        Object.entries(apiKeys).map(([key, value]) => [key, value || null])
      )
      const response = await api.updateApiKeys(payload)

      setNotice({
        type: 'success',
        message: response.message,
      })

      // Reload provider status after update — a newly saved key can flip a
      // provider from disabled to enabled, or clear a cooldown it was under.
      const [providerList, keysStatus, availabilityList] = await Promise.all([
        api.getProviderStatus(),
        api.getApiKeysStatus(),
        api.getProviderAvailability(),
      ])
      setProviders(providerList)
      setApiKeysStatus(keysStatus)
      setAvailability(availabilityList)
    } catch (err) {
      setNotice({
        type: 'error',
        message: t('settings.error', { error: String(err) }),
      })
    } finally {
      setBusy(false)
    }
  }, [apiKeys, t])

  const handleKeyChange = useCallback((providerName: string, value: string) => {
    setApiKeys((prev) => ({
      ...prev,
      [providerName]: value,
    }))
    // A fresh edit invalidates any earlier test result for this field —
    // otherwise a stale "✓ valid" can sit next to a since-edited, untested value.
    setTestResults((prev) => {
      if (!(providerName in prev)) return prev
      const next = { ...prev }
      delete next[providerName]
      return next
    })
  }, [])

  const handleTest = useCallback(
    async (providerName: string) => {
      setTestResults((prev) => ({ ...prev, [providerName]: 'testing' }))
      try {
        const result = await api.verifyApiKey(providerName, apiKeys[providerName])
        setTestResults((prev) => ({ ...prev, [providerName]: result }))
      } catch (err) {
        setTestResults((prev) => ({
          ...prev,
          [providerName]: { valid: false, message: err instanceof Error ? err.message : String(err) },
        }))
      }
    },
    [apiKeys],
  )

  // Only providers with an actual key field belong on this page: the keyless
  // ones (Yahoo, Boursorama, Frankfurt, Eoddata, Finviz) are always on
  // and have nothing here to configure — listing them would just be clutter
  // with no control behind it.
  const keyedProviders = providers.filter((p) => p.has_api_key)
  const keylessProviders = providers.filter((p) => !p.has_api_key)
  const availabilityByName = new Map(availability.map((a) => [a.name, a]))

  if (loading) {
    return (
      <div className="page-header">
        <h1>{t('settings.title')}</h1>
        <p>{t('common.loading')}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="page-header">
        <h1>{t('settings.title')}</h1>
        <p>{t('settings.subtitle')}</p>
      </div>

      <section className="settings-group" id="donnees-portefeuille">
        <h2>{t('settings.groupPortfolioData.title')}</h2>
        <p className="muted">{t('settings.groupPortfolioData.subtitle')}</p>

        <ImportPanel kind="xtb" onImported={() => {}} />
        <ImportPanel kind="mintos" onImported={() => {}} />
        <ImportPanel kind="mintos-investments" onImported={() => {}} />
        <ImportPanel kind="amundi" onImported={() => {}} />
        <ImportPanel kind="amundi-synthese" onImported={() => {}} />
        <FundamentalsRefreshButton onRefreshed={() => {}} />
        <ManualPositionForm onCreated={() => {}} />
      </section>

      <section className="settings-group" id="integrite-corrections">
        <h2>{t('settings.groupIntegrity.title')}</h2>
        <p className="muted">{t('settings.groupIntegrity.subtitle')}</p>

        <DataHealthPanel />
        <UnresolvedPanel instruments={unresolvedInstruments} onUpdated={() => void loadUnresolved()} />
        <CorporateActionsPanel />
      </section>

      <section className="settings-group" id="sauvegarde">
        <h2>{t('settings.groupBackup.title')}</h2>

        <BackupPanel />
      </section>

      <section className="settings-group" id="sources-donnees">
        <h2>{t('settings.groupDataSources.title')}</h2>
        <p className="muted">{t('settings.groupDataSources.subtitle')}</p>

      <div className="card">
        <p>{t('settings.description')}</p>
      </div>

      <div className="card">
        <h2>{t('settings.providerStatus')}</h2>

        <div className="providers-list">
          {keyedProviders.map((provider) => {
            // Not a secret like the others — it's a contact identifier SEC
            // EDGAR requires on every request, sent openly in a header. A
            // password-masked field would just hide typos in your own email.
            const isContactField = provider.name === 'sec_user_agent'

            return (
            <div key={provider.name} className="provider-row">
              <div className="provider-info">
                <h3>{isContactField ? t('settings.secEdgarName') : provider.name}</h3>
                <p>{provider.description}</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                  <span className={`status-badge ${provider.enabled ? 'enabled' : 'disabled'}`}>
                    {provider.enabled ? t('settings.enabled') : t('settings.disabled')}
                  </span>
                  <ProviderAvailabilityInfo availability={availabilityByName.get(provider.name)} />
                  {provider.signup_url && (
                    <a href={provider.signup_url} target="_blank" rel="noopener noreferrer" className="signup-link">
                      {isContactField ? t('settings.learnMore') : t('settings.getFreeKey')} ↗
                    </a>
                  )}
                </div>
              </div>

              <div className="form-row" style={{ alignItems: 'flex-end' }}>
                <div className="field">
                  <label htmlFor={`key-${provider.name}`}>
                    {isContactField ? t('settings.contactInfo') : t('settings.apiKey')}
                  </label>
                  <input
                    id={`key-${provider.name}`}
                    type={isContactField ? 'text' : 'password'}
                    style={isContactField ? { width: '300px' } : undefined}
                    placeholder={
                      apiKeysStatus[provider.name]
                        ? isContactField
                          ? t('settings.contactInfoSet')
                          : '●●●●●●●●●●●●'
                        : isContactField
                          ? t('settings.noContactInfo')
                          : t('settings.noKey')
                    }
                    value={apiKeys[provider.name] || ''}
                    onChange={(e) => handleKeyChange(provider.name, e.target.value)}
                    disabled={busy}
                  />
                  {isContactField && (
                    <span className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
                      {t('settings.contactInfoFormat')}
                    </span>
                  )}
                </div>
                <button
                  onClick={() => void handleTest(provider.name)}
                  disabled={
                    busy ||
                    testResults[provider.name] === 'testing' ||
                    (!apiKeys[provider.name] && !apiKeysStatus[provider.name])
                  }
                >
                  {testResults[provider.name] === 'testing' ? t('settings.testing') : t('settings.test')}
                </button>
              </div>

              <TestResultLine result={testResults[provider.name]} />
            </div>
            )
          })}
        </div>

        <p className="muted keyless-note">
          {t('settings.keylessNote', { names: keylessProviders.map((p) => p.name).join(', ') })}
        </p>

        {keylessProviders.length > 0 && (
          <ul className="keyless-availability">
            {keylessProviders.map((provider) => (
              <li key={provider.name}>
                <span>{provider.name}</span>
                <ProviderAvailabilityInfo availability={availabilityByName.get(provider.name)} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="form-row" style={{ marginTop: 'var(--space-4)' }}>
        <button
          className="primary"
          onClick={handleSave}
          disabled={busy}
        >
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>

      {notice && (
        <div className={`card notice ${notice.type}`}>
          {notice.message}
        </div>
      )}
      </section>
    </div>
  )
}

/** Whether a source is currently rate-limited, and how much of the held
 * portfolio it covers — undefined while `/api/prices/providers` is still
 * loading, or for a provider that endpoint doesn't (yet) list. */
function ProviderAvailabilityInfo({ availability }: { availability: ProviderAvailability | undefined }) {
  const { t } = useI18n()
  if (!availability) return null

  const nearLimit =
    availability.quota_limit !== null &&
    availability.quota_used !== null &&
    availability.quota_used / availability.quota_limit >= 0.8

  return (
    <>
      {availability.cooling_down && (
        <span className="status-badge cooling-down" title={t('settings.coolingDownTooltip')}>
          {t('settings.coolingDown')}
        </span>
      )}
      {availability.quota_limit !== null && availability.quota_used !== null && (
        <span className={`muted quota-note${nearLimit ? ' near-limit' : ''}`}>
          {t('settings.quotaUsed', {
            used: availability.quota_used,
            limit: availability.quota_limit,
            period:
              availability.quota_period === 'month'
                ? t('settings.periodMonth')
                : availability.quota_period === 'minute'
                  ? t('settings.periodMinute')
                  : t('settings.periodDay'),
          })}
        </span>
      )}
      {availability.total_holdings > 0 && (
        <span className="muted coverage-note">
          {t('settings.coverage', {
            served: availability.serves_holdings,
            total: availability.total_holdings,
          })}
        </span>
      )}
    </>
  )
}

function TestResultLine({ result }: { result: TestResult | undefined }) {
  if (!result || result === 'testing') return null

  return (
    <p className={`test-result ${result.valid ? 'valid' : 'invalid'}`}>
      {result.valid ? '✓' : '✗'} {result.message}
    </p>
  )
}
