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
