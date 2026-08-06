/** Footer — V4 design. Ported verbatim from the mock. */
import { Wordmark } from '../../ds/index.js'

export function LandingFooter() {
  return (
    <div style={{ borderTop: '1px solid var(--hairline)' }}>
      <div style={{ maxWidth: 1120, margin: '0 auto', padding: '22px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14 }}>
        <Wordmark size={12} />
        <span style={{ fontSize: 12.5, color: 'var(--faint)' }}>© 2026 Parleo, Inc.</span>
        <span className="mono-label" style={{ fontSize: 10, color: 'var(--faint)' }}>audit.parleo.io</span>
      </div>
    </div>
  )
}
