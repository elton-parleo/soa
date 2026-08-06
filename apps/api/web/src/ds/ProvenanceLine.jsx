/**
 * Methodology footer: where a number comes from. Mono microtext, comma
 * separators, confidence tag. Ported from the exported design-system
 * bundle (components/foundation/ProvenanceLine.jsx) — same render tree,
 * restored to JSX.
 */
export function ProvenanceLine({ parts = [], confidence, dark = false, style }) {
  const mut = dark ? 'var(--dark-faint)' : 'var(--faint)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.04em', color: mut, ...style }}>
      {confidence ? (
        <span
          style={{
            padding: '1px 8px',
            borderRadius: 999,
            border: `1px solid ${confidence === 'observed' ? 'var(--green)' : 'var(--border-strong)'}`,
            color: confidence === 'observed' ? 'var(--green)' : mut,
            textTransform: 'uppercase',
            fontSize: 11,
          }}
        >
          {confidence}
        </span>
      ) : null}
      <span>{parts.join(', ')}</span>
    </div>
  )
}
