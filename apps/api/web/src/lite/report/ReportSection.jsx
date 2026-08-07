import { SectionCollapseButton } from './SectionCollapseButton.jsx'

export function ReportSection({ id, eyebrow, title, score, extra, open, onToggle, children }) {
  return (
    <div
      id={id}
      className="lite-report-section"
      style={{
        background: 'var(--surface)', borderRadius: 16, boxShadow: 'var(--shadow-card)',
        padding: '26px 28px', marginBottom: 16, scrollMarginTop: 26,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
        <div className="lite-report-section-title" style={{ flex: 1, minWidth: 220 }}>
          <div className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)' }}>{eyebrow}</div>
          <h2 className="card-heading" style={{ margin: '7px 0 0' }}>{title}</h2>
        </div>
        {extra}
        {score != null && (
          <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: 'var(--text-strong)' }}>
            {score}
          </span>
        )}
        <SectionCollapseButton open={open} onClick={onToggle} />
      </div>
      {open && <div className="sec-body">{children}</div>}
    </div>
  )
}
