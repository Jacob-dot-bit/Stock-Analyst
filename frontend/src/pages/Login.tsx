import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import { LanguageSwitcher } from '../components/LanguageSwitcher'
import { ThemeToggle } from '../components/ThemeToggle'
import { useI18n } from '../i18n'

// Backend codes (backend/app/auth/service.py) the form knows how to explain.
const KNOWN_ERRORS = new Set(['auth.invalidCredentials', 'auth.locked', 'auth.notConfigured'])

interface Props {
  /** No account exists yet: say how to create one instead of a dead form. */
  notConfigured: boolean
  onLoggedIn: () => void | Promise<void>
}

export function Login({ notConfigured, onLoggedIn }: Props) {
  const { t } = useI18n()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  // The code field appears once the backend asks for it, so an account
  // without the 6-digit code never sees an empty, puzzling field.
  const [needsCode, setNeedsCode] = useState(false)
  const [error, setError] = useState<string | null>(notConfigured ? t('auth.notConfigured') : null)
  const [busy, setBusy] = useState(false)
  const codeInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    document.title = `${t('auth.title')} · ${t('app.title')}`
  }, [t])

  useEffect(() => {
    if (needsCode) codeInput.current?.focus()
  }, [needsCode])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.login(username.trim(), password, needsCode ? code.trim() : undefined)
      setPassword('')
      setCode('')
      await onLoggedIn()
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      if (message === 'auth.totpRequired') {
        // First step passed, or a wrong code: both look the same on purpose.
        setError(needsCode ? t('auth.invalidCredentials') : null)
        setNeedsCode(true)
        setCode('')
      } else if (message === 'auth.locked') {
        const minutes = Math.max(1, Math.ceil(((err instanceof ApiError && err.retryAfter) || 60) / 60))
        setError(t('auth.locked', { count: minutes }))
      } else if (KNOWN_ERRORS.has(message)) {
        setError(t(message))
        if (needsCode) setCode('')
      } else {
        setError(t('auth.unreachable', { detail: message }))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-controls">
        <LanguageSwitcher />
        <ThemeToggle />
      </div>
      <form className="card login-card" onSubmit={submit} noValidate>
        <h1>{t('app.title')}</h1>
        <p className="muted">{t('auth.subtitle')}</p>

        {error && (
          <div className="notice error" role="alert">
            {error}
          </div>
        )}

        <div className="field">
          <label htmlFor="login-username">{t('auth.username')}</label>
          <input
            id="login-username"
            name="username"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            autoFocus
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={busy || needsCode}
          />
        </div>

        <div className="field">
          <label htmlFor="login-password">{t('auth.password')}</label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy || needsCode}
          />
        </div>

        {needsCode && (
          <div className="field">
            <label htmlFor="login-code">{t('auth.code')}</label>
            <input
              id="login-code"
              ref={codeInput}
              name="code"
              autoComplete="one-time-code"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={6}
              required
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              disabled={busy}
            />
            <span className="muted login-hint">{t('auth.codeHint')}</span>
          </div>
        )}

        <button
          type="submit"
          className="primary"
          disabled={busy || !username.trim() || !password || (needsCode && code.length !== 6)}
        >
          {busy ? t('auth.signingIn') : t('auth.signIn')}
        </button>

        {needsCode && (
          <button
            type="button"
            className="link"
            onClick={() => {
              setNeedsCode(false)
              setCode('')
              setPassword('')
              setError(null)
            }}
          >
            {t('auth.back')}
          </button>
        )}
      </form>
    </div>
  )
}
