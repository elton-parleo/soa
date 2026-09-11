/** Footer — V4 design. Ported verbatim from the mock, plus the
 * tracking-disclosure line (Part 1d) — this is the audit footer's
 * one place that discloses analytics/tracking on the page. It now
 * covers two tags: the lemlist visitor pixel (outreach attribution)
 * and the OpenAI Measurement Pixel (ad conversion measurement). One
 * sentence, both purposes named. */
import { WordmarkLink } from '../WordmarkLink.jsx'
import { PUBLIC_AUDIT_DISPLAY } from '../publicUrls.js'

export function LandingFooter() {
  return (
    <div style={{ borderTop: '1px solid var(--hairline)' }}>
      <div className="lite-landing-footer-row" style={{ maxWidth: 1120, margin: '0 auto', padding: '22px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14 }}>
        <WordmarkLink size={12} />
        <span style={{ fontSize: 12.5, color: 'var(--faint)' }}>© 2026 Parleo, Inc.</span>
        <span className="mono-label" style={{ fontSize: 10, color: 'var(--faint)' }}>{PUBLIC_AUDIT_DISPLAY}</span>
      </div>
      <div style={{ maxWidth: 1120, margin: '0 auto', padding: '0 24px 18px' }}>
        <span style={{ fontSize: 11, color: 'var(--faint)' }}>This page uses visitor tracking for outreach attribution and ad conversion measurement.</span>
      </div>
    </div>
  )
}
