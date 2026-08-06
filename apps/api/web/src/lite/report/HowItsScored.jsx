import { Glyph, StateChip } from '../../ds/index.js'
import { toChipState } from './checkState.js'

export function HowItsScoredButton({ open, onToggle }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 9, background: 'var(--surface)',
        border: '1px solid var(--border-strong)', borderRadius: 10, padding: '6px 13px 6px 7px',
        cursor: 'pointer', fontFamily: 'inherit', fontSize: 12.5, fontWeight: 580,
        letterSpacing: '-0.008em', color: 'var(--text-strong)', boxShadow: 'var(--shadow-sm)',
      }}
    >
      <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, flexShrink: 0, borderRadius: 7, background: 'var(--blue-tint)' }}>
        <Glyph name={open ? 'x' : 'plus'} size={11} color="var(--blue)" />
      </span>
      How it's scored
    </button>
  )
}

// Prose-only panel — still used for Value Protocols, which the mock
// keeps as a single caption rather than a chip grid (its checks render
// unconditionally above the expander, not inside it).
export function HowItsScoredPanel({ children }) {
  return (
    <div style={{ marginTop: 13, background: 'var(--surface)', border: '1px solid var(--hairline)', borderRadius: 12, padding: '14px 16px' }}>
      <span className="mono-label" style={{ display: 'block', fontSize: 9, color: 'var(--faint)', marginBottom: 9 }}>HOW WE MEASURE</span>
      <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{children}</div>
    </div>
  )
}

// 1a: Price Truth / Member Value / Deal Citability's "How it's scored"
// panel — one StateChip per run check (label + state straight from the
// serialized payload, so nothing here is a JS-literal claim about the
// run), plus the registry's one-line scoredCaption underneath. checks
// is the dimension's real `checks` array (server-computed, already
// interpolates run counts into the label — see lite_pillars.py's
// _price_truth_checks/_member_value_checks/_deal_citability_checks);
// caption is the registry's scoredCaption ({text, bold}[]).
export function HowItsScoredChips({ checks, caption }) {
  return (
    <div style={{ marginTop: 13, background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 12, padding: '14px 16px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {(checks || []).map((c) => (
          <StateChip key={c.code} state={toChipState(c.state)} variant="chip" size="sm">{c.label}</StateChip>
        ))}
      </div>
      {caption && (
        <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6, marginTop: 12 }}>
          {caption.map((seg, i) => (
            <span key={i} style={seg.bold ? { color: 'var(--text-strong)', fontWeight: 640 } : undefined}>{seg.text}</span>
          ))}
        </div>
      )}
    </div>
  )
}
