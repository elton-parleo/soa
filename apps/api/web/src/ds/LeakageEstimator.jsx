/**
 * Deal Leakage Estimator: dark hero number + stacked cause bars. Ported
 * from the exported design-system bundle
 * (components/artifacts/LeakageEstimator.jsx) — same render tree,
 * restored to JSX.
 */
import { Stat } from './Stat.jsx'
import { ProvenanceLine } from './ProvenanceLine.jsx'

export function LeakageEstimator({ total = '4.8', prefix = '$', suffix = 'M', label = 'Annual deal leakage', causes = [], provenance, style }) {
  const sum = causes.reduce((s, c) => s + c.value, 0) || 1
  const colors = ['var(--red)', 'var(--amber)', 'var(--blue-lite)', 'rgba(242,240,239,.35)']

  return (
    <div className="atmos-cool-dark" style={{ background: 'var(--ink)', borderRadius: 16, padding: '28px 30px', color: 'var(--dark-text)', overflow: 'hidden', ...style }}>
      <Stat value={total} prefix={prefix} suffix={suffix} label={label} size={54} dark countUp />
      <div style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', gap: 2, margin: '22px 0 14px' }}>
        {causes.map((c, i) => (
          <div key={i} style={{ width: `${(c.value / sum) * 100}%`, background: c.color || colors[i % colors.length], borderRadius: 3 }} />
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {causes.map((c, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2.5, background: c.color || colors[i % colors.length], flexShrink: 0 }} />
            <span style={{ color: 'var(--dark-muted)', flex: 1 }}>{c.label}</span>
            <span className="num" style={{ fontWeight: 640 }}>{c.display}</span>
          </div>
        ))}
      </div>
      {provenance ? <ProvenanceLine parts={provenance} confidence="modeled" dark style={{ marginTop: 18 }} /> : null}
    </div>
  )
}
