/**
 * Dark ink panel for high-value metrics, critical recommendations,
 * dramatic moments. Never flat: pass `image` for photography under the
 * ink wash (grain included), or keep the cool atmospheric wash.
 * tone: ink | code. Ported from the exported design-system bundle
 * (components/layout/DarkPanel.jsx) — same render tree, restored to JSX.
 */
export function DarkPanel({ children, pad = 32, radius = 16, tone = 'ink', atmos = true, noise = false, image, position = 'center', style }) {
  if (image) {
    return (
      <div className="ink-photo" style={{ borderRadius: radius, padding: pad, color: 'var(--dark-text)', ...style }}>
        <img src={image} alt="" style={{ objectPosition: position }} />
        {children}
      </div>
    )
  }
  return (
    <div
      className={`${atmos ? 'atmos-cool-dark' : ''}${noise ? ' noise-bg' : ''}`}
      style={{ background: tone === 'code' ? 'var(--code-bg)' : 'var(--ink)', color: 'var(--dark-text)', borderRadius: radius, padding: pad, overflow: 'hidden', ...style }}
    >
      {children}
    </div>
  )
}
