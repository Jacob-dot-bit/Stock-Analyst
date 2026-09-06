import { useI18n } from '../i18n'

export interface ColumnDef {
  key: string
  /** Already-resolved display text, not an i18n key — some column labels
   * take interpolation params (e.g. a currency code) only the caller has. */
  label: string
}

interface Props {
  columns: ColumnDef[]
  hidden: Set<string>
  onToggle: (key: string) => void
}

/** Checkbox list of hideable columns, in a small popover. */
export function ColumnPicker({ columns, hidden, onToggle }: Props) {
  const { t } = useI18n()

  return (
    <details className="column-picker">
      <summary>{t('table.columns')}</summary>
      <div className="column-picker-menu">
        {columns.map((col) => (
          <label key={col.key}>
            <input type="checkbox" checked={!hidden.has(col.key)} onChange={() => onToggle(col.key)} />
            {col.label}
          </label>
        ))}
      </div>
    </details>
  )
}
