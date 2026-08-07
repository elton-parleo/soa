/**
 * Sample report — V4 design. BrowserChrome frame around a miniature
 * replica of the sample report's score panel + OfferFeed, linking out
 * to SAMPLE_REPORT_URL. Ported verbatim from the mock; sample numbers
 * are the canonical 40/100 (Visibility 25/40, Accessibility 8/20, True
 * Value 7/40) run, same as landingSampleContent.js.
 */
import { BrowserChrome, BrandLogo, StatusChip, MetricRow, OfferFeed, Button, SectionHeading } from '../../ds/index.js'
import { SAMPLE_REPORT_URL, SAMPLE_PILLAR_ITEMS, SAMPLE_OFFERS } from './landingSampleContent.js'

function ScorePanel() {
  return (
    <a
      href={SAMPLE_REPORT_URL}
      className="atmos-cool-dark"
      style={{ display: 'block', position: 'relative', background: 'var(--ink)', padding: '26px 26px 24px', overflow: 'hidden', textDecoration: 'none' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <BrandLogo name="Allbirds" domain="allbirds.com" size={16} />
        <span style={{ fontSize: 13, fontWeight: 620, color: 'var(--dark-text)' }}>Allbirds</span>
      </div>
      <div style={{ marginTop: 22 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
          <span className="num lite-display-num" style={{ fontSize: 52, fontWeight: 750, letterSpacing: '-0.044em', lineHeight: 0.86, color: 'var(--dark-text)', fontVariantNumeric: 'tabular-nums' }}>40</span>
          <span className="num" style={{ fontSize: 19, fontWeight: 560, color: 'var(--dark-faint)' }}>/100</span>
        </div>
        <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--dark-faint)', marginTop: 9 }}>AGENTIC VALUE SCORE</div>
        <div style={{ marginTop: 20 }}>
          <div style={{ background: 'var(--canvas)', borderRadius: 12, padding: '16px 16px 13px', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.7),0 8px 20px -10px rgba(10,10,18,.55)' }}>
            <div style={{ position: 'relative', height: 11, borderRadius: 5.5, background: 'var(--canvas-dim)', boxShadow: 'inset 0 1px 2px rgba(70,69,85,.16),inset 0 0 0 1px rgba(213,209,203,.95)' }}>
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '40%', borderRadius: 5.5, background: 'var(--ink)', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.16)' }} />
              <span aria-hidden="true" style={{ position: 'absolute', left: '40%', top: -2, bottom: -2, width: 3, transform: 'translateX(-3px)', borderRadius: 2, background: 'var(--blue)', boxShadow: '0 0 10px rgba(1,102,255,.6)' }} />
              <span aria-hidden="true" style={{ position: 'absolute', left: '60%', top: -4, bottom: -4, width: 1, background: 'var(--text-strong)' }} />
              <span aria-hidden="true" style={{ position: 'absolute', left: '60%', top: -8, width: 5, height: 5, transform: 'translateX(-2px)', background: 'var(--text-strong)', clipPath: 'polygon(0 0,100% 0,50% 100%)' }} />
            </div>
            <div style={{ position: 'relative', height: 14, marginTop: 7 }}>
              <span className="mono-label" style={{ position: 'absolute', left: 0, top: 0, fontSize: 9, color: 'var(--text-strong)', fontWeight: 600 }}>40 EARNED</span>
              <span className="mono-label" style={{ position: 'absolute', left: '60%', top: 0, transform: 'translateX(-50%)', fontSize: 9, color: 'var(--muted)', whiteSpace: 'nowrap' }}>READY 60</span>
              <span className="mono-label" style={{ position: 'absolute', right: 0, top: 0, fontSize: 9, color: 'var(--faint)' }}>100</span>
            </div>
          </div>
        </div>
        <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--dark-border)' }}>
          <StatusChip tone="risk" size="sm">Not agent-ready</StatusChip>
          <div className="mono-label" style={{ fontSize: 9, color: 'var(--dark-faint)', marginTop: 11, lineHeight: 1.7 }}>
            20 POINTS BELOW READY<br />2ND OF 6 IN ITS COMPETITOR SET
          </div>
        </div>
      </div>
    </a>
  )
}

export function SampleReportSection() {
  return (
    <section style={{ padding: '66px 24px 12px' }}>
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <SectionHeading
          size="sm"
          accent="in one report."
          body="One number, a verdict, and every point traced back to what an agent actually read on your site."
        >
          Every gap you have,
        </SectionHeading>
        <div style={{ marginTop: 30 }}>
          <BrowserChrome url="audit.parleo.io/r/allbirds" chip="SAMPLE" shadow="elevated" radius={16}>
            <div className="lite-sample-grid" style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 0, background: 'var(--surface)' }}>
              <ScorePanel />
              <div style={{ padding: '24px 26px' }}>
                <MetricRow items={SAMPLE_PILLAR_ITEMS} size={34} />
                <div style={{ marginTop: 20, borderTop: '1px solid var(--hairline)', paddingTop: 16 }}>
                  <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', marginBottom: 11 }}>WHAT AGENTS COULD SEE OF YOUR VALUE</div>
                  <OfferFeed offers={SAMPLE_OFFERS} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 18, flexWrap: 'wrap' }}>
                  <a href={SAMPLE_REPORT_URL} style={{ textDecoration: 'none' }}>
                    <Button variant="blue" arrow>Open the full sample report</Button>
                  </a>
                  <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)' }}>MODELED EXPOSURE $775K / YR</span>
                </div>
              </div>
            </div>
          </BrowserChrome>
        </div>
      </div>
    </section>
  )
}
