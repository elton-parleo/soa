/**
 * Sticky landing nav — V4 design. Wordmark + "Free Agentic Value Audit"
 * label, sample-report link + Run-my-free-audit button. Ported from the
 * mock's Nav section (Audit Landing.dc.html) verbatim.
 */
import { Wordmark, Button } from '../../ds/index.js'
import { SAMPLE_REPORT_URL } from './landingSampleContent.js'

export function LandingNav() {
  return (
    <nav aria-label="Parleo Audit" style={{ position: 'sticky', top: 0, zIndex: 60, background: 'rgba(242,240,239,.86)', backdropFilter: 'blur(12px)', borderBottom: '1px solid var(--hairline)' }}>
      <div style={{ maxWidth: 1120, margin: '0 auto', padding: '14px 24px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <Wordmark size={15} />
        <span style={{ width: 1, height: 15, background: 'var(--border)' }} />
        <span style={{ fontSize: 13.5, fontWeight: 520, color: 'var(--text)' }}>Free Agentic Value Audit</span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 18 }}>
          <a href={SAMPLE_REPORT_URL} style={{ fontSize: 13.5, fontWeight: 500, color: 'var(--text)' }}>See a sample report</a>
          <a href="#run" style={{ textDecoration: 'none' }}>
            <Button variant="blue" size="sm" arrow>Run my free audit</Button>
          </a>
        </div>
      </div>
    </nav>
  )
}
