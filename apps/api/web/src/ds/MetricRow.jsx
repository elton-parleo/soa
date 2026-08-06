/**
 * Editorial stat band: 2-4 numbers with hairline dividers and mono
 * captions. Numbers lead. Ported from the exported design-system bundle
 * (components/data/MetricRow.jsx) — same render tree, restored to JSX.
 */
import { Stat } from './Stat.jsx'

export function MetricRow({ items = [], size = 56, dark = false, countUp = true, style }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${items.length},1fr)`, gap: 0, ...style }}>
      {items.map((it, i) => (
        <div
          key={i}
          style={{
            padding: '4px 32px 4px 0',
            marginLeft: i > 0 ? 32 : 0,
            borderLeft: i > 0 ? `1px solid ${dark ? 'var(--dark-border)' : 'var(--border)'}` : 'none',
            paddingLeft: i > 0 ? 32 : 0,
          }}
        >
          <Stat value={it.value} prefix={it.prefix} suffix={it.suffix} delta={it.delta} deltaTone={it.deltaTone} size={size} dark={dark} countUp={countUp} accent={it.accent} />
          <div style={{ fontSize: 13.5, fontWeight: 560, color: dark ? 'var(--dark-text)' : 'var(--text-strong)', marginTop: 12, letterSpacing: '-0.01em' }}>{it.label}</div>
          {it.sub ? <div className="mono-label" style={{ color: dark ? 'var(--dark-faint)' : 'var(--faint)', marginTop: 5, fontSize: 11 }}>{it.sub}</div> : null}
        </div>
      ))}
    </div>
  )
}
