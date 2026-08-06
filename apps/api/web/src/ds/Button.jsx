/**
 * Pill button with machined lift (btn-lift), optional sliding arrow.
 * Ported from the exported design-system bundle
 * (components/controls/Button.jsx) — same render tree, restored to JSX.
 */
const VARIANTS = {
  ink: { background: 'var(--ink)', color: '#fff', border: '1px solid transparent' },
  blue: { background: 'var(--blue)', color: '#fff', border: '1px solid transparent' },
  outline: { background: 'rgba(255,255,255,.55)', color: 'var(--text-strong)', border: '1px solid var(--border-strong)' },
  ghost: { background: 'transparent', color: 'var(--text)', border: '1px solid transparent' },
  light: { background: '#fff', color: 'var(--ink)', border: '1px solid transparent' },
}

export function Button({ children, variant = 'ink', size = 'md', arrow = false, onClick, disabled = false, style }) {
  const v = VARIANTS[variant] || VARIANTS.ink
  const pad = size === 'sm' ? '7px 16px' : size === 'lg' ? '14px 30px' : '11px 24px'
  const fs = size === 'sm' ? 13 : size === 'lg' ? 15 : 14
  return (
    <button
      className="btn-lift"
      onClick={onClick}
      disabled={disabled}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        whiteSpace: 'nowrap',
        borderRadius: 999,
        fontFamily: 'var(--font-sans)',
        fontSize: fs,
        fontWeight: 520,
        letterSpacing: '-0.005em',
        padding: pad,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        ...v,
        ...style,
      }}
    >
      <span>{children}</span>
      {arrow ? <span className="btn-arrow" aria-hidden="true">→</span> : null}
    </button>
  )
}
