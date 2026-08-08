import { Container, MonoTag, Button, RequestFormModal } from '../../ds/index.js'
import { TRUESYNC_BAND_COPY } from './reportContent.js'
import { useDemoRequestModal } from '../useDemoRequestModal.js'

export function TrueSyncBand({ points, brandName, reportToken }) {
  const demoModal = useDemoRequestModal({ brandName, reportToken })
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
          <Button variant="blue" arrow onClick={() => demoModal.open('truesync')}>Talk to us about TrueSync</Button>
        </div>
      </Container>
      {demoModal.cta && (
        <RequestFormModal
          open={demoModal.isOpen}
          onClose={demoModal.close}
          eyebrow={demoModal.cta.eyebrow}
          title={demoModal.cta.title}
          messagePlaceholder={demoModal.cta.messagePlaceholder}
          onSubmit={demoModal.onSubmit}
        />
      )}
    </div>
  )
}
