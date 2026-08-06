/**
 * Window chrome for product mockups. variant browser = traffic lights +
 * URL pill; app = traffic lights + title. Ported from the exported
 * design-system bundle (components/layout/BrowserChrome.jsx) — same
 * render tree, restored to JSX.
 */
import { Glyph } from './Glyph.jsx'

export function BrowserChrome({ children, url = 'parleo.io', title, variant = 'browser', dark = false, shadow = 'elevated', radius = 14, chip, style, bodyStyle }) {
  const barBg = dark ? 'rgba(255,255,255,.04)' : 'var(--surface-warm)'
  const line = dark ? 'var(--dark-border)' : 'var(--border)'
  return (
    <div style={{ background: dark ? 'var(--code-bg)' : 'var(--surface)', borderRadius: radius, boxShadow: `var(--shadow-${shadow})`, overflow: 'hidden', ...style }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: barBg, borderBottom: `1px solid ${line}` }}>
        <span style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          {['#F65F57', '#FBBD2E', '#28C840'].map((c) => (
            <span key={c} style={{ width: 10, height: 10, borderRadius: '50%', background: c, opacity: dark ? 0.9 : 1 }} />
          ))}
        </span>
        {variant === 'browser' ? (
          <span
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
              maxWidth: 320,
              margin: '0 auto',
              padding: '4px 12px',
              borderRadius: 999,
              background: dark ? 'rgba(255,255,255,.07)' : 'var(--canvas)',
              border: `1px solid ${line}`,
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: dark ? 'var(--dark-muted)' : 'var(--muted)',
            }}
          >
            <svg width="9" height="10" viewBox="0 0 9 10" fill="none" stroke="currentColor" strokeWidth="1.1">
              <rect x="1" y="4.2" width="7" height="5" rx="1.2" />
              <path d="M2.6 4V3a1.9 1.9 0 1 1 3.8 0v1" />
            </svg>
            {url}
          </span>
        ) : (
          <span style={{ flex: 1, textAlign: 'center', fontSize: 12, fontWeight: 540, color: dark ? 'var(--dark-muted)' : 'var(--text)', letterSpacing: '-0.005em' }}>{title}</span>
        )}
        <span style={{ width: 40, flexShrink: 0, display: 'flex', justifyContent: 'flex-end', color: dark ? 'var(--dark-faint)' : 'var(--faint)' }}>
          {chip || <Glyph name="plus" size={11} />}
        </span>
      </div>
      <div style={bodyStyle}>{children}</div>
    </div>
  )
}
