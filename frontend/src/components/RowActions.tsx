import { useI18n } from '../i18n'

interface Props {
  editing: boolean
  busy: boolean
  onEdit: () => void
  onDelete: () => void
  onSave: () => void
  onCancel: () => void
}

/** The "Edit / Delete" links of a table row, or "Save / Cancel" while it is
 * being edited — the watchlist and gems tables' last column. */
export function RowActions({ editing, busy, onEdit, onDelete, onSave, onCancel }: Props) {
  const { t } = useI18n()
  if (editing) {
    return (
      <>
        <button className="link" disabled={busy} onClick={onSave}>
          {busy ? t('common.saving') : t('common.save')}
        </button>{' '}
        <button className="link" disabled={busy} onClick={onCancel}>
          {t('common.cancel')}
        </button>
      </>
    )
  }
  return (
    <>
      <button className="link" onClick={onEdit}>
        {t('common.edit')}
      </button>{' '}
      <button className="link" onClick={onDelete}>
        {t('common.delete')}
      </button>
    </>
  )
}
