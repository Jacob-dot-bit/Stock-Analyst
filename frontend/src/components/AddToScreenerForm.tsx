import { useState } from 'react'
import { api } from '../api/client'
import { useI18n } from '../i18n'
import { SymbolInput } from './SymbolInput'

interface Props {
  onCreated: () => void
}

export function AddToScreenerForm({ onCreated }: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)

  const valid = symbol.trim().length > 0

  async function submit() {
    setBusy(true)
    setError(null)
    setWarning(null)
    try {
      const created = await api.addScreenerCandidate({
        broker_symbol: symbol.trim().toUpperCase(),
        company_name: companyName.trim() || null,
      })
      setSymbol('')
      setCompanyName('')
      onCreated()
      // A duplicate warning is a soft signal, not an error — the item was
      // still added. Keep the form open so the user actually reads it.
      if (created.duplicate_warning) {
        setWarning(created.duplicate_warning)
      } else {
        setOpen(false)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="compact">{t('gems.form.title')}</h2>
            <span className="muted">{t('gems.form.subtitle')}</span>
          </div>
          <button onClick={() => setOpen(true)}>{t('common.add')}</button>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <h2>{t('gems.form.newTitle')}</h2>

      <div className="form-row">
        <SymbolInput
          id="sc-symbol"
          label={t('gems.form.symbol')}
          value={symbol}
          onChange={setSymbol}
          onPick={(result) => setCompanyName(result.name)}
        />
        <div className="field">
          <label htmlFor="sc-company">{t('gems.form.companyName')}</label>
          <input
            id="sc-company"
            value={companyName}
            placeholder={t('gems.form.companyNamePlaceholder')}
            onChange={(e) => setCompanyName(e.target.value)}
          />
        </div>
        <button className="primary" disabled={!valid || busy} onClick={() => void submit()}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
        <button onClick={() => setOpen(false)}>{t('common.cancel')}</button>
      </div>

      {error && (
        <div className="notice error" style={{ marginTop: '0.8rem', marginBottom: 0 }}>
          {error}
        </div>
      )}
      {warning && (
        <div className="notice warning" style={{ marginTop: '0.8rem', marginBottom: 0 }}>
          {warning}
        </div>
      )}
    </div>
  )
}
