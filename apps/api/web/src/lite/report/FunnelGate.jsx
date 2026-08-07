import { Button, StatusChip } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { FUNNEL_GATE_COPY, FULL_ANALYSIS_URL } from './reportContent.js'

const STAGES = ['AWARENESS', 'CONSIDERATION', 'COMPARISON', 'READY TO BUY']
const STAGE_HEIGHTS = [76, 56, 34, 13]

export function FunnelGate({ open, onToggle }) {
  return (
    <ReportSection
      id="fun" eyebrow={FUNNEL_GATE_COPY.eyebrow} title={FUNNEL_GATE_COPY.title}
      extra={<StatusChip tone="warning" size="sm">Full Analysis</StatusChip>}
      open={open} onToggle={onToggle}
    >
      <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 8 }}>{FUNNEL_GATE_COPY.body}</div>
      <div style={{ position: 'relative', borderRadius: 14, background: 'var(--surface-warm)', border: '1px dashed var(--border-strong)', padding: '22px 20px 16px', marginTop: 16 }}>
        <div aria-hidden="true" className="lite-funnel-bars-row" style={{ display: 'flex', gap: 16, alignItems: 'flex-end', height: 120, filter: 'blur(3.5px)', opacity: 0.72 }}>
          {STAGES.map((label, i) => (
            <span key={label} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%', textAlign: 'center' }}>
              <b className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 500, color: i === 3 ? 'var(--red-deep)' : 'var(--faint)', marginBottom: 6 }}>··%</b>
              <i style={{ display: 'block', background: i === 3 ? 'var(--red-tint)' : 'var(--canvas-dim)', boxShadow: `inset 0 0 0 1px ${i === 3 ? 'rgba(239,67,67,.2)' : 'var(--hairline)'}`, borderRadius: '6px 6px 0 0', height: STAGE_HEIGHTS[i] }} />
              <u className="mono-label" style={{ textDecoration: 'none', fontSize: 9, color: i === 3 ? 'var(--red-deep)' : 'var(--muted)', marginTop: 8 }}>{label}</u>
            </span>
          ))}
        </div>
        <span className="mono-label" style={{ position: 'absolute', top: 14, right: 16, fontSize: 9, letterSpacing: '.18em', fontWeight: 600, color: 'var(--amber-deep)', border: '1.5px solid var(--amber)', borderRadius: 999, padding: '5px 13px 4px', background: 'rgba(255,255,255,.94)', whiteSpace: 'nowrap' }}>MEASURED IN THE FULL ANALYSIS</span>
      </div>
      <div style={{ marginTop: 22, paddingTop: 20, borderTop: '1px solid var(--hairline)', display: 'flex', justifyContent: 'space-between', gap: 28, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ maxWidth: 530 }}>
          <h3 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-strong)', margin: 0, letterSpacing: '-0.016em' }}>{FUNNEL_GATE_COPY.ctaHeading}</h3>
          <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.65, marginTop: 8 }}>{FUNNEL_GATE_COPY.ctaBody}</div>
          <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--faint)', marginTop: 12, lineHeight: 1.7 }}>{FUNNEL_GATE_COPY.ctaFooter}</div>
        </div>
        <a href={FULL_ANALYSIS_URL} style={{ textDecoration: 'none', flexShrink: 0 }}>
          <Button variant="blue" size="lg" arrow>Book your walkthrough</Button>
        </a>
      </div>
    </ReportSection>
  )
}
