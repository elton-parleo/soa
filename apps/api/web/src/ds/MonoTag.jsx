/**
 * Small mono technical tag. pill = white chip with hairline + shadow
 * (marquee rails); plain = bare mono label. Ported from the exported
 * design-system bundle (components/foundation/MonoTag.jsx) — same
 * render tree, restored to JSX.
 */
import { BrandLogo } from './BrandLogo.jsx'

export function MonoTag({ children, logo, tone = 'pill', style }) {
  const base = {
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    fontWeight: 500,
    letterSpacing: '0.07em',
    textTransform: 'uppercase',
    color: 'var(--text)',
    whiteSpace: 'nowrap',
  }
  if (tone === 'plain') {
    return <span style={{ ...base, color: 'var(--muted)', ...style }}>{children}</span>
  }
  if (tone === 'blue') {
    return (
      <span style={{ ...base, display: 'inline-flex', alignItems: 'center', gap: 7, padding: '5px 12px', borderRadius: 999, background: 'var(--blue)', color: '#fff', ...style }}>
        {logo ? <BrandLogo name={logo} size={13} /> : null}
        {children}
      </span>
    )
  }
  if (tone === 'dark') {
    return (
      <span style={{ ...base, display: 'inline-flex', alignItems: 'center', gap: 7, padding: '5px 12px', borderRadius: 999, background: 'var(--ink)', color: 'var(--dark-text)', ...style }}>
        {logo ? <BrandLogo name={logo} size={13} /> : null}
        {children}
      </span>
    )
  }
  return (
    <span style={{ ...base, display: 'inline-flex', alignItems: 'center', gap: 7, padding: '5px 12px', borderRadius: 999, background: 'var(--surface)', boxShadow: 'var(--shadow-card)', ...style }}>
      {logo ? <BrandLogo name={logo} size={13} /> : null}
      {children}
    </span>
  )
}
