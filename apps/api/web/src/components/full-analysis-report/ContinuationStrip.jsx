/**
 * Continuation strip — new (no lite equivalent). Reads report.
 * continuation (FullAnalysisContinuation): audit_composite/date for the
 * "continuing from your audit" line, pillar_deltas for the per-pillar
 * chips. A pillar whose delta isn't comparable (true_value — the
 * deal_citability rate-band rescore at full-cycle volume, see
 * _PILLAR_DELTA_COMPARABLE's backend docstring) shows "Rescored at full
 * scale" instead of a number — never a false-precision delta.
 */
import { Glyph } from '../../ds/index.js'
import { NAV_IDS } from './fullAnalysisNav.js'

const PILLAR_LABELS = { visibility: 'Visibility', accessibility: 'Accessibility', true_value: 'True Value' }

function DeltaChip({ delta }) {
  const { pillar, delta: value, comparable } = delta
  let text, color
  if (!comparable) {
    text = 'RESCORED AT FULL SCALE'
    color = 'var(--muted)'
  } else if (value > 0) {
    text = `▲ ${value.toFixed(1)} PTS`
    color = 'var(--green)'
  } else if (value < 0) {
    text = `▼ ${Math.abs(value).toFixed(1)} PTS`
    color = 'var(--red-deep)'
  } else {
    text = '= FLAT'
    color = 'var(--muted)'
  }
  return (
    <div style={{ textAlign: 'center' }}>
      <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)' }}>{PILLAR_LABELS[pillar]}</div>
      <div className="mono-label" style={{ fontSize: 11, fontWeight: 600, marginTop: 4, color }}>{text}</div>
    </div>
  )
}

export function ContinuationStrip({ continuation, platformsNote }) {
  if (!continuation) return null
  return (
    <div id={NAV_IDS.CONTINUATION} style={{
      background: 'var(--blue-tint)', border: '1.5px solid rgba(1,102,255,.35)', borderRadius: 16,
      marginBottom: 18, padding: '18px 24px', display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap',
      scrollMarginTop: 26,
    }}>
      <div style={{ flex: '1 1 360px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <Glyph name="refresh" size={16} color="var(--blue-deep)" />
        <div>
          <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--blue-deep)' }}>
            CONTINUED FROM YOUR AUDIT{continuation.audit_date ? ` · ${continuation.audit_date}` : ''}
          </span>
          <div style={{ fontSize: 13.5, color: 'var(--text)', marginTop: 6, lineHeight: 1.55 }}>
            Your free audit ({platformsNote}) scored{' '}
            {continuation.audit_composite != null ? <b className="num" style={{ fontFamily: 'var(--font-mono)' }}>{continuation.audit_composite}</b> : 'not yet'}
            . This full analysis re-measures the same rubric at real scale.
          </div>
        </div>
      </div>
      {(continuation.pillar_deltas || []).map((d) => <DeltaChip key={d.pillar} delta={d} />)}
    </div>
  )
}
