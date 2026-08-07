/**
 * Partial-read report state (Part 5b): "what a complete read adds" —
 * renders only in partial_read (caller-gated), reuses the funnel
 * gate's dashed-tile idiom but is explicitly NOT gated behind the Full
 * Analysis — these tiles are waiting on fix 01, not payment. Copy from
 * reportContent.js's COMPLETE_READ_BAND_COPY, never hardcoded here.
 */
import { COMPLETE_READ_BAND_COPY } from './reportContent.js'

export function CompleteReadBand() {
  const { eyebrow, title, body, tiles } = COMPLETE_READ_BAND_COPY
  return (
    <div style={{ background: 'var(--surface)', borderRadius: 16, boxShadow: 'var(--shadow-card)', padding: '26px 28px', marginBottom: 16 }}>
      <div className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)' }}>{eyebrow}</div>
      <h2 className="card-heading" style={{ margin: '9px 0 0' }}>{title}</h2>
      <div style={{ fontSize: 13.5, color: 'var(--muted)', lineHeight: 1.6, marginTop: 8, maxWidth: 620 }}>{body}</div>
      <div className="lite-complete-read-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginTop: 20 }}>
        {tiles.map((t) => (
          <div key={t.title} style={{ border: '1px dashed var(--border-strong)', borderRadius: 12, padding: '14px 15px', background: 'var(--surface-warm)' }}>
            <div style={{ fontSize: 12.5, fontWeight: 640, color: 'var(--text-strong)' }}>{t.title}</div>
            <div style={{ fontSize: 11.5, color: 'var(--faint)', marginTop: 6, lineHeight: 1.5 }}>{t.body}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
