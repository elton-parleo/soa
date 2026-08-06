import { Container, MonoTag, Button } from '../../ds/index.js'
import { TRUESYNC_BAND_COPY, TRUESYNC_URL } from './reportContent.js'

export function TrueSyncBand({ points }) {
  return (
    <div id="truesync" style={{ marginBottom: 16, scrollMarginTop: 26 }}>
      <Container pad={0}>
        <div style={{ padding: '22px 26px 24px', display: 'flex', justifyContent: 'space-between', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ maxWidth: 540 }}>
            <MonoTag tone="blue">TRUESYNC</MonoTag>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-strong)', letterSpacing: '-0.018em', marginTop: 12 }}>{TRUESYNC_BAND_COPY.title}</div>
            <div style={{ fontSize: 13.5, color: 'var(--muted)', lineHeight: 1.6, marginTop: 7 }}>{TRUESYNC_BAND_COPY.body}</div>
            {points != null && (
              <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--faint)', marginTop: 13, lineHeight: 1.7 }}>
                RECOVERS UP TO {Math.round(points)} VALUE POINTS ON THIS RUN, AND THE CHECKOUT REVENUE BEHIND THEM
              </div>
            )}
          </div>
          <a href={TRUESYNC_URL} style={{ textDecoration: 'none' }}>
            <Button variant="blue" arrow>Talk to us about TrueSync</Button>
          </a>
        </div>
      </Container>
    </div>
  )
}
