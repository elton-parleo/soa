import { DarkPanel, Container, MonoTag, Button } from '../../ds/index.js'
import { CLOSING_FORK_COPY, FULL_ANALYSIS_URL, TRUESYNC_URL } from './reportContent.js'

export function ClosingFork({ points }) {
  return (
    <div id="next" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24, scrollMarginTop: 26 }}>
      <DarkPanel pad="24px 26px" radius={16} atmos>
        <MonoTag tone="dark">FULL ANALYSIS</MonoTag>
        <h3 style={{ fontSize: 19, fontWeight: 700, color: 'var(--dark-text)', margin: '14px 0 8px', letterSpacing: '-0.016em' }}>{CLOSING_FORK_COPY.fullAnalysisTitle}</h3>
        <div style={{ fontSize: 13, color: 'var(--dark-muted)', lineHeight: 1.65 }}>{CLOSING_FORK_COPY.fullAnalysisBody}</div>
        <div style={{ marginTop: 18 }}>
          <a href={FULL_ANALYSIS_URL} style={{ textDecoration: 'none' }}><Button variant="blue" arrow>Book your walkthrough</Button></a>
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
          <a href={TRUESYNC_URL} style={{ textDecoration: 'none' }}><Button variant="outline" arrow>Talk to us about TrueSync</Button></a>
        </div>
        {points != null && (
          <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--faint)', marginTop: 14 }}>RECOVERS UP TO {Math.round(points)} VALUE POINTS ON THIS RUN</div>
        )}
      </Container>
    </div>
  )
}
