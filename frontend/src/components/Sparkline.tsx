interface Props {
  closes: number[]
  width?: number
  height?: number
}

/**
 * A minimal trend line drawn as inline SVG.
 *
 * No chart library: this needs a polyline and a colour, and a dependency would cost
 * more than it gives. The line is coloured by the direction over the window, which is
 * the only thing readable at this size — a precise reading belongs in the numbers next
 * to it, not here.
 */
export function Sparkline({ closes, width = 68, height = 22 }: Props) {
  if (closes.length < 2) return <span className="muted">—</span>

  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const span = max - min

  const points = closes
    .map((close, index) => {
      const x = (index / (closes.length - 1)) * width
      // A flat series would divide by zero; centre it instead of collapsing to the top.
      const y = span === 0 ? height / 2 : height - ((close - min) / span) * height
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  const rising = closes[closes.length - 1] >= closes[0]
  const stroke = rising ? 'var(--positive)' : 'var(--negative)'

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-hidden="true"
      style={{ display: 'block', overflow: 'visible' }}
    >
      <polyline points={points} fill="none" stroke={stroke} strokeWidth="1.5" />
    </svg>
  )
}
