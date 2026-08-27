import type { SignalValue } from '../api/types'

/**
 * A visible label for `_position_signal`/`GET /.../signals`'s output.
 *
 * Deliberately renders a *fact* the caller composes ("high score ·
 * under-allocated"), never a verb — "Reinforce"/"Reduce" still read as
 * instructions even without saying "Buy"/"Sell" (caught on review, see
 * DEVLOG "Decision 3u.19"'s addendum). Both convergence cases ("reinforce"
 * and "reduce") share one "worth a look" color rather than a green/red
 * pair, matching `AllocationTargets.tsx`'s own under/over convention — the
 * point is to flag that two independent signals line up, not to imply
 * which direction is "good".
 */
export function SignalBadge({ signal, label, title }: { signal: SignalValue; label: string; title: string }) {
  const className = signal === 'reinforce' || signal === 'reduce' ? 'tag unresolved' : 'tag neutral'

  return (
    <span className={className} title={title}>
      {label}
    </span>
  )
}
