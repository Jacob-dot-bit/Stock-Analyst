import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { en } from './en'
import { fr } from './fr'
import { pl } from './pl'
import { LOCALES, type Catalogue, type Locale, type Translation } from './types'

const CATALOGUES: Record<Locale, Catalogue> = { en, fr, pl }

const STORAGE_KEY = 'stock-analyst.locale'

export type TranslateParams = Record<string, string | number | string[]>

interface I18nValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: string, params?: TranslateParams) => string
  formatNumber: (value: number | null | undefined, digits?: number) => string
  formatSignedPercent: (value: number | null | undefined) => string
  formatDate: (value: string | null | undefined) => string
}

const I18nContext = createContext<I18nValue | null>(null)

/** Detect a supported locale from the browser, falling back to English. */
function detectLocale(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored && (LOCALES as readonly string[]).includes(stored)) return stored as Locale

  for (const candidate of navigator.languages ?? [navigator.language]) {
    const base = candidate.split('-')[0]
    if ((LOCALES as readonly string[]).includes(base)) return base as Locale
  }
  return 'en'
}

/** Replace {placeholders}. Arrays are joined — symbol lists arrive that way. */
function interpolate(template: string, params: TranslateParams): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = params[name]
    if (value === undefined) return match
    return Array.isArray(value) ? value.join(', ') : String(value)
  })
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(detectLocale)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, locale)
    // Keeps screen readers and browser features (translation offers, hyphenation)
    // in sync with what is actually rendered.
    document.documentElement.lang = locale
  }, [locale])

  const pluralRules = useMemo(() => new Intl.PluralRules(locale), [locale])

  const t = useCallback(
    (key: string, params: TranslateParams = {}): string => {
      // Fall back to English before giving up: a missing translation should degrade
      // to a readable sentence, not to a raw identifier.
      const entry: Translation | undefined = CATALOGUES[locale][key] ?? en[key]
      if (entry === undefined) return key

      if (typeof entry === 'string') return interpolate(entry, params)

      const count = Number(params.count ?? 0)
      const category = pluralRules.select(count)
      const template = entry[category] ?? entry.other ?? Object.values(entry)[0]
      return template ? interpolate(template, params) : key
    },
    [locale, pluralRules],
  )

  const numberFormats = useMemo(
    () => ({
      two: new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      upToFour: new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }),
      date: new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit', year: 'numeric' }),
    }),
    [locale],
  )

  const value = useMemo<I18nValue>(() => {
    // A missing value renders as an em dash, never as "0": unknown is not zero.
    const formatNumber = (input: number | null | undefined, digits = 2) => {
      if (input === null || input === undefined) return '—'
      return digits === 2 ? numberFormats.two.format(input) : numberFormats.upToFour.format(input)
    }

    return {
      locale,
      setLocale: setLocaleState,
      t,
      formatNumber,
      formatSignedPercent: (input) => {
        if (input === null || input === undefined) return '—'
        return `${input > 0 ? '+' : ''}${numberFormats.two.format(input)} %`
      },
      formatDate: (input) => {
        if (!input) return '—'
        const date = new Date(input)
        return Number.isNaN(date.getTime()) ? '—' : numberFormats.date.format(date)
      },
    }
  }, [locale, t, numberFormats])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const context = useContext(I18nContext)
  if (context === null) throw new Error('useI18n must be used inside <I18nProvider>')
  return context
}

export { LOCALES, LOCALE_LABELS } from './types'
export type { Locale } from './types'

// Development guard: a key present in English but missing elsewhere would silently
// fall back to English and go unnoticed. Failing loudly at load is cheaper to fix.
if (import.meta.env.DEV) {
  for (const locale of LOCALES) {
    if (locale === 'en') continue
    const missing = Object.keys(en).filter((key) => !(key in CATALOGUES[locale]))
    if (missing.length > 0) {
      console.warn(`[i18n] "${locale}" is missing ${missing.length} key(s):`, missing)
    }
  }
}
