import { useCallback, useState } from 'react'

export interface SortState<K extends string> {
  key: K
  direction: 'asc' | 'desc'
}

/** A clickable column header — click sorts by this column (ascending first),
 * click again reverses direction, clicking a different column switches to it
 * (ascending first again). Generic over the caller's own sort-key union, so
 * each table (positions, watchlist, ...) keeps its own small key type instead
 * of sharing one that would have to cover every column across all of them. */
export function SortableHeader<K extends string>({
  label,
  sortKeyName,
  sort,
  onSort,
  className,
  title,
}: {
  label: string
  sortKeyName: K
  sort: SortState<K>
  onSort: (key: K) => void
  className?: string
  title?: string
}) {
  const active = sort.key === sortKeyName
  // The click target is a real <button> inside the <th> (not an onClick on
  // the cell itself), so the header is reachable with Tab and activates with
  // Enter/Space; aria-sort tells a screen reader which column orders the rows.
  return (
    <th
      className={`sortable${className ? ` ${className}` : ''}${active ? ' sorted' : ''}`}
      title={title}
      aria-sort={active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button type="button" className="sort-button" onClick={() => onSort(sortKeyName)}>
        {label}
        <span className="sort-arrow" aria-hidden="true">
          {active ? (sort.direction === 'asc' ? '▲' : '▼') : ''}
        </span>
      </button>
    </th>
  )
}

/** Sort state for a table: clicking a column sorts by it ascending, clicking
 * it again reverses direction. */
export function useSort<K extends string>(initial: SortState<K>): [SortState<K>, (key: K) => void] {
  const [sort, setSort] = useState<SortState<K>>(initial)
  const onSort = useCallback((key: K) => {
    setSort((prev) => (prev.key === key ? { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' } : { key, direction: 'asc' }))
  }, [])
  return [sort, onSort]
}

/** `rows` sorted by `valueOf(row, sort.key)`, as a new array. Missing values
 * always sort last, regardless of direction — the same "never guess"
 * convention this app applies everywhere else: a blank isn't the lowest or
 * highest value, it's unknown. */
export function sortRows<T, K extends string>(
  rows: T[],
  sort: SortState<K>,
  valueOf: (row: T, key: K) => string | number | null | undefined,
): T[] {
  const dir = sort.direction === 'asc' ? 1 : -1
  return rows.slice().sort((a, b) => {
    const av = valueOf(a, sort.key)
    const bv = valueOf(b, sort.key)
    if (av === null || av === undefined) return bv === null || bv === undefined ? 0 : 1
    if (bv === null || bv === undefined) return -1
    if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv) * dir
    return ((av as number) - (bv as number)) * dir
  })
}
