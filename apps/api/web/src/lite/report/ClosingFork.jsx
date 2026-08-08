import { DarkPanel, Container, MonoTag, Button, RequestFormModal } from '../../ds/index.js'
import { CLOSING_FORK_COPY } from './reportContent.js'
import { useDemoRequestModal } from '../useDemoRequestModal.js'

export function ClosingFork({ points, brandName, reportToken }) {
  const demoModal = useDemoRequestModal({ brandName, reportToken })
  return (
    <div id="next" className="lite-closingfork-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24, scrollMarginTop: 26 }}>
      <DarkPanel pad="24px 26px" radius={16} atmos>
        <MonoTag tone="dark">FULL ANALYSIS</MonoTag>
        <h3 style={{ fontSize: 19, fontWeight: 700, color: 'var(--dark-text)', margin: '14px 0 8px', letterSpacing: '-0.016em' }}>{CLOSING_FORK_COPY.fullAnalysisTitle}</h3>
        <div style={{ fontSize: 13, color: 'var(--dark-muted)', lineHeight: 1.65 }}>{CLOSING_FORK_COPY.fullAnalysisBody}</div>
        <div style={{ marginTop: 18 }}>
          <Button variant="blue" arrow onClick={() => demoModal.open('full_analysis_walkthrough')}>Book your walkthrough</Button>
        </div>
        <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--dark-faint)', marginTop: 14, lineHeight: 1.7 }}>TAKES ONE CALL TO SCOPE · READ-OUT IN DAYS<br />NO INTEGRATION, NO OBLIGATION</div>
      </DarkPanel>
      <Container pad="24px 26px">
        <MonoTag tone="blue">TRUESYNC</MonoTag>
        <h3 style={{ fontSize: 19, fontWeight: 700, color: 'var(--text-strong)', margin: '14px 0 4px', letterSpacing: '-0.016em' }}>{CLOSING_FORK_COPY.trueSyncTitle}</h3>
        <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.65 }}>{CLOSING_FORK_COPY.trueSyncBody}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 16 }}>
          {CLOSING_FORK_COPY.steps.map((s) => (
            <div key={s.title} style={{ borderLeft: '2px solid var(--blue)', paddingLeft: 13 }}>
              <b style={{ display: 'block', fontSize: 13.5, color: 'var(--text-strong)' }}>{s.title}</b>
              <span style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.55 }}>{s.body}</span>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 18 }}>
          <Button variant="outline" arrow onClick={() => demoModal.open('truesync')}>Talk to us about TrueSync</Button>
        </div>
        {points != null && (
          <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--faint)', marginTop: 14 }}>RECOVERS UP TO {Math.round(points)} VALUE POINTS ON THIS RUN</div>
        )}
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
