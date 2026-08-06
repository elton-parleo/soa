import { GROUNDED_COPY } from './reportContent.js'

export function ReportGrounded() {
  return (
    <div style={{ borderTop: '1px solid var(--hairline)', paddingTop: 20, marginBottom: 22, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28 }}>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.7 }}>
        <b style={{ color: 'var(--text-strong)' }}>Every number here is measured.</b> {GROUNDED_COPY.measured.replace('Every number here is measured. ', '')}
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.7 }}>
        <b style={{ color: 'var(--text-strong)' }}>Already running Profound or Bluelight? Keep them.</b> {GROUNDED_COPY.keepThem.replace('Already running Profound or Bluelight? Keep them. ', '')}
      </div>
    </div>
  )
}
