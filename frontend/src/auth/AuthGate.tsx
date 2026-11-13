import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, SESSION_LOST_EVENT, api } from '../api/client'
import type { AuthMe } from '../api/types'
import { SkeletonPage } from '../components/Skeleton'
import { Login } from '../pages/Login'

type Phase =
  | { kind: 'checking' }
  | { kind: 'in'; me: AuthMe | null }
  | { kind: 'login'; notConfigured: boolean }

interface AuthValue {
  /** Null when the app is open without a login (none required, none set up). */
  me: AuthMe | null
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

/**
 * Shows the login page or the app.
 *
 * The backend is the one that refuses calls; this only decides what to draw.
 * Logged in: the app. Not logged in: the login page, as soon as an account
 * exists or the backend requires one. With neither (a fresh install), the
 * app opens as before.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>({ kind: 'checking' })

  const check = useCallback(async () => {
    try {
      setPhase({ kind: 'in', me: await api.authMe() })
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 401) {
        // Backend down or another failure: let the pages show it as usual.
        setPhase({ kind: 'in', me: null })
        return
      }
      try {
        const status = await api.authStatus()
        if (status.required || status.configured) {
          setPhase({ kind: 'login', notConfigured: !status.configured })
        } else {
          setPhase({ kind: 'in', me: null })
        }
      } catch {
        setPhase({ kind: 'login', notConfigured: false })
      }
    }
  }, [])

  useEffect(() => {
    void check()
  }, [check])

  // A call refused mid-visit (idle for 7 days, logged out from another tab,
  // password changed) brings the login page back instead of an error.
  useEffect(() => {
    const onLost = () => setPhase({ kind: 'login', notConfigured: false })
    window.addEventListener(SESSION_LOST_EVENT, onLost)
    return () => window.removeEventListener(SESSION_LOST_EVENT, onLost)
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setPhase({ kind: 'login', notConfigured: false })
    }
  }, [])

  const me = phase.kind === 'in' ? phase.me : null
  const value = useMemo<AuthValue>(() => ({ me, logout }), [me, logout])

  if (phase.kind === 'checking') return <SkeletonPage />
  if (phase.kind === 'login') return <Login notConfigured={phase.notConfigured} onLoggedIn={check} />
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext)
  if (context === null) throw new Error('useAuth must be used inside <AuthGate>')
  return context
}
