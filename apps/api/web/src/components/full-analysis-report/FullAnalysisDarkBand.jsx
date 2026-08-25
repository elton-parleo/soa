/**
 * Dark CTA band — mirrors TrueSyncBand.jsx's tone/markup, not reused
 * directly: TrueSyncBand's CTA opens useDemoRequestModal, which posts
 * to the public lead-gen demo-request endpoint keyed by a lite report
 * token (soa_lite_requests.token) — meaningless in this authenticated,
 * cycle_code-keyed context. No authenticated equivalent exists yet, so
 * this is a plain link the caller can point wherever cycle-level
 * "talk to us" actions already live, rather than wiring a lead-gen flow
 * into the paid product.
 *
 * fix/full-analysis-rail-nav: this sibling never carried lite's own
 * TrueSyncBand.jsx id="truesync" — the rail's "TrueSync" nav item, and
 * FixableHook.jsx's "headline finding" link (shared with lite, always
 * `#truesync`), both pointed here and found nothing. Confirmed live —
 * clicking either did nothing.
 */
import { Glyph } from '../../ds/index.js'
import { NAV_IDS } from './fullAnalysisNav.js'

export function FullAnalysisDarkBand({ fixCount, contactHref = 'mailto:hello@parleo.com' }) {
  return (
    <div id={NAV_IDS.TRUESYNC} style={{
      background: 'linear-gradient(150deg,#181D28,#12161F)', borderRadius: 20, padding: '30px 34px',
      color: '#fff', marginBottom: 18, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 20, flexWrap: 'wrap',
      scrollMarginTop: 26,
    }}>
      <div>
        <div className="mono-label" style={{ fontSize: 9, color: '#6C7482', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Glyph name="refresh" size={13} color="var(--blue-lite)" /> BEFORE YOUR NEXT CYCLE
        </div>
        <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1.2, maxWidth: 540 }}>
          {fixCount > 0
            ? `${fixCount} of your ranked fixes are TrueSync's lane. Turn them on, then re-measure.`
            : 'Re-run this analysis after your next change to see the delta.'}
        </div>
      </div>
      <a href={contactHref} style={{ background: 'var(--blue)', color: '#fff', border: 'none', borderRadius: 12, padding: '14px 22px', fontSize: 14.5, fontWeight: 600, textDecoration: 'none' }}>
        Talk to us about TrueSync →
      </a>
    </div>
  )
}
