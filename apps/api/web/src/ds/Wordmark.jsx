/**
 * PARLEO lockup: two-bar glyph + heavy wordmark. Never typeset the
 * wordmark alone. Ported from the exported design-system bundle
 * (components/foundation/Wordmark.jsx) — same render tree, restored to
 * JSX.
 */
export function Wordmark({ size = 15, dark = false, glyphOnly = false, style }) {
  const g = size * 1.05
  const glyph = (
    <svg width={g * 1.15} height={g} viewBox="0 0 46 40" style={{ display: 'block', flexShrink: 0 }}>
      <rect x="0" y="0" width="19" height="40" rx="6" fill="#0166FF" />
      <rect x="27" y="9" width="15" height="22" rx="5" fill="#7FB0FF" />
    </svg>
  )
  if (glyphOnly) return <span style={{ display: 'inline-flex', ...style }}>{glyph}</span>
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.55, ...style }}>
      {glyph}
      <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 800, fontSize: size, letterSpacing: '0.015em', color: dark ? 'var(--dark-text)' : 'var(--ink)', lineHeight: 1 }}>PARLEO</span>
    </span>
  )
}
