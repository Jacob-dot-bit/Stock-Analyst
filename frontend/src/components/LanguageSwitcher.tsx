import { LOCALES, LOCALE_LABELS, useI18n, type Locale } from '../i18n'

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n()

  return (
    <label className="language-switcher">
      <span className="visually-hidden">{t('language.label')}</span>
      <select
        value={locale}
        aria-label={t('language.label')}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        {LOCALES.map((code) => (
          // Language names stay in their own language: someone looking for "Polski"
          // should not have to know the word for it in the current interface language.
          <option key={code} value={code}>
            {LOCALE_LABELS[code]}
          </option>
        ))}
      </select>
    </label>
  )
}
