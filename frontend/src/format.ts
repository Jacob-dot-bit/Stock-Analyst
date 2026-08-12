/**
 * Locale-independent presentation helpers.
 *
 * Anything that depends on the user's language — number, date and plural formatting —
 * lives in `i18n/` instead, bound to the active locale.
 */

/** CSS class for a signed figure. Zero and unknown stay neutral, never green or red. */
export function signClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return ''
  return value > 0 ? 'positive' : 'negative'
}
