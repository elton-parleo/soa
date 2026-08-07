import { SectionCollapseButton } from './SectionCollapseButton.jsx'

// accentColor (Part 3, discovery finding): an optional top border —
// additive, undefined by default so every existing caller renders
// byte-identically. borderTop can't just append onto boxShadow's own
// border(-adjacent) styling, so it's spread in only when passed.
export function ReportSection({ id, eyebrow, title, score, extra, open, onToggle, children, accentColor }) {
  return (
    <div
      id={id}
      className="lite-report-section"
      style={{
        background: 'var(--surface)', borderRadius: 16, boxShadow: 'var(--shadow-card)',
        padding: '26px 28px', marginBottom: 16, scrollMarginTop: 26,
        ...(accentColor ? { borderTop: `3px solid ${accentColor}` } : null),
      }}
    >
      <div className="lite-report-section-header" style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
        <div className="lite-report-section-title" style={{ flex: 1, minWidth: 220 }}>
          <div className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)' }}>{eyebrow}</div>
          <h2 className="card-heading" style={{ margin: '7px 0 0' }}>{title}</h2>
        </div>
        {/* Grouped (rather than extra/score/collapse as three direct flex
            children, as before) so the phone override below can drop all
            three onto their own wrapped row below the title with one
            rule — display:contents at desktop keeps this wrapper
            invisible to layout, so the three items stay direct flex
            items of .lite-report-section-header exactly as before,
            byte-identical. */}
        <div className="lite-report-section-controls" style={{ display: 'contents' }}>
          {extra}
          {score != null && (
            <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: 'var(--text-strong)' }}>
              {score}
            </span>
          )}
          <SectionCollapseButton open={open} onClick={onToggle} />
        </div>
      </div>
      {open && <div className="sec-body">{children}</div>}
    </div>
  )
}
