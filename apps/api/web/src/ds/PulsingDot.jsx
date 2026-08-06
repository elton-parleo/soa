/**
 * Live-status dot. Pairs with mono context labels. Internal dependency
 * of StatusChip — not in D2's named component list, ported alongside
 * it. Ported from the exported design-system bundle
 * (components/foundation/PulsingDot.jsx) — same render tree, restored
 * to JSX.
 */
export function PulsingDot({ color = 'var(--blue)', size = 8, pulse = true, style }) {
  return (
    <span
      className={pulse ? 'animate-pulse-dot' : undefined}
      style={{ display: 'inline-block', width: size, height: size, borderRadius: '50%', background: color, flexShrink: 0, ...style }}
    />
  )
}
