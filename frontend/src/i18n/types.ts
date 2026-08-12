export const LOCALES = ['en', 'fr', 'pl'] as const

export type Locale = (typeof LOCALES)[number]

/** Native language names, shown in the switcher — deliberately never translated. */
export const LOCALE_LABELS: Record<Locale, string> = {
  en: 'English',
  fr: 'Français',
  pl: 'Polski',
}

/**
 * A translation entry.
 *
 * Most entries are a plain string. Entries that vary with a count are an object keyed
 * by CLDR plural category, resolved through `Intl.PluralRules`: English has two forms,
 * French two, and Polish three (`one`, `few`, `many`). Writing
 * `count === 1 ? singular : plural` would be wrong in Polish for 2–4, and wrong again
 * from 5 upwards.
 */
export type Translation = string | Partial<Record<Intl.LDMLPluralRule, string>>

export type Catalogue = Record<string, Translation>
