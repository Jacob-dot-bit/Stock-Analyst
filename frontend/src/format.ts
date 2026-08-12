const numberFormat = new Intl.NumberFormat('fr-FR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** Une valeur absente s'affiche « — », jamais « 0 » : l'inconnu n'est pas un zéro. */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return numberFormat.format(value)
}

export function formatMoney(value: number | null | undefined, currency: string | null): string {
  if (value === null || value === undefined) return '—'
  return `${numberFormat.format(value)}${currency ? ` ${currency}` : ''}`
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value > 0 ? '+' : ''}${numberFormat.format(value)} %`
}

export function formatQuantity(value: number): string {
  return new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 4 }).format(value)
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function signClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return ''
  return value > 0 ? 'positive' : 'negative'
}
