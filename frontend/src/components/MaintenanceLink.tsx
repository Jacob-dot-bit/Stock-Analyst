import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'

/** Where a view's catch-up action now lives: the Settings "Data updates" tab
 * (DEVLOG "Step 3u.99"). Shown where the button used to be, so the action
 * stays one click away without being repeated on every page. */
export function MaintenanceLink() {
  const { t } = useI18n()
  return (
    <Link className="maintenance-link" to="/settings#mise-a-jour">
      {t('maintenance.link')}
    </Link>
  )
}
