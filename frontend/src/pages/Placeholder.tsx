import { useI18n } from '../i18n'

interface Props {
  titleKey: string
  descriptionKey: string
  phaseKey: string
}

export function Placeholder({ titleKey, descriptionKey, phaseKey }: Props) {
  const { t } = useI18n()

  return (
    <>
      <div className="page-header">
        <h1>{t(titleKey)}</h1>
        <p>{t(descriptionKey)}</p>
      </div>

      <div className="card">
        <div className="empty">{t('placeholder.comingIn', { phase: t(phaseKey) })}</div>
      </div>
    </>
  )
}
