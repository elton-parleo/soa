/**
 * Tinted delta pill. Direction from sign; tone override for "down is
 * good" metrics. Internal dependency of SoAIndex — not in D2's named
 * component list, ported alongside it since SoAIndex renders it for
 * any row.delta. Ported from the exported design-system bundle
 * (components/foundation/Delta.jsx) — same render tree, restored to JSX.
 */
export function Delta({ value, tone, suffix = '%', bare = false, size = 'md', style }) {
  const up = value > 0
  const flat = value === 0
  const good = tone ? tone === 'good' : up
  const fg = flat ? 'var(--muted)' : good ? 'var(--green)' : 'var(--red-deep)'
  const bg = flat ? 'var(--canvas-dim)' : good ? 'var(--green-tint)' : 'var(--red-tint)'
  const arrow = flat ? '→' : up ? '↑' : '↓'
  const txt = `${arrow} ${Math.abs(value)}${suffix}`
  if (bare) {
    return <span className="num" style={{ color: fg, fontSize: size === 'sm' ? 11 : 12.5, fontWeight: 600, ...style }}>{txt}</span>
  }
  return (
    <span
      className="num"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: size === 'sm' ? '1px 7px' : '2px 9px',
        borderRadius: 999,
        background: bg,
        color: fg,
        fontSize: size === 'sm' ? 10.5 : 12,
        fontWeight: 600,
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {txt}
    </span>
  )
}
