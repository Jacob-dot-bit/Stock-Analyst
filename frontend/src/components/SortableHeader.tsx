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
  return (
    <th
      className={`sortable${className ? ` ${className}` : ''}${active ? ' sorted' : ''}`}
      title={title}
      onClick={() => onSort(sortKeyName)}
    >
      {label}
      <span className="sort-arrow">{active ? (sort.direction === 'asc' ? '▲' : '▼') : ''}</span>
    </th>
  )
}
