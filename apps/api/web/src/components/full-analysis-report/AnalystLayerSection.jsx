/**
 * Analyst layer — new (no lite equivalent; lite never had enough volume
 * for a slice breakdown). Reuses the EXISTING /api/metrics/{cycleCode}
 * endpoint (api.getMetrics, app/routers/metrics.py) — the same slices
 * shape MetricsDashboard.jsx already renders elsewhere — rather than a
 * bespoke full-analysis-only metrics query. One fetch on mount; the tab
 * and sub-value pickers only ever re-slice data already in memory.
 */
import { useEffect, useState } from 'react'
import { api } from '../../api.js'
import { ReportSection } from '../../lite/report/ReportSection.jsx'

const TABS = [
  { key: 'overall', label: 'Overall' },
  { key: 'by_stage', label: 'By Stage' },
  { key: 'by_category', label: 'By Category' },
  { key: 'by_platform', label: 'By Platform' },
  { key: 'by_persona', label: 'By Persona' },
]

const METRIC_ROWS = [
  { key: 'mention_rate', label: 'Mention Rate', suffix: '%' },
  { key: 'som', label: 'Share of Mentions', suffix: '%' },
  { key: 'rsi', label: 'Recommendation Strength', suffix: '' },
  { key: 'position_index', label: 'Position Index', suffix: '' },
  { key: 'pdi', label: 'Platform Distribution', suffix: '' },
  { key: 'deal_citation_rate', label: 'Incentive Citation Rate', suffix: '%' },
]

function fmt(value, suffix) {
  if (value == null) return '—'
  return suffix ? `${Math.round(value * 10) / 10}${suffix}` : `${Math.round(value * 100) / 100}`
}

export function AnalystLayerSection({ cycleCode, open, onToggle }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('overall')
  const [subValue, setSubValue] = useState(null)

  useEffect(() => {
    api.getMetrics(cycleCode).then(setData).catch((err) => setError(err.message))
  }, [cycleCode])

  if (error) return null
  if (!data) {
    return (
      <ReportSection id="analyst" eyebrow="ANALYST LAYER · SAME METRICS AS EVERY PAST CYCLE" title="The six core metrics, every slice" open={open} onToggle={onToggle}>
        <div style={{ color: 'var(--faint)', fontSize: 13, marginTop: 16 }}>Loading analyst metrics…</div>
      </ReportSection>
    )
  }

  const sliceForTab = tab === 'overall' ? { overall: data.slices.overall } : (data.slices[tab] || {})
  const subValues = tab === 'overall' ? ['overall'] : Object.keys(sliceForTab).sort()
  const activeSubValue = tab === 'overall' ? 'overall' : (subValue && subValues.includes(subValue) ? subValue : subValues[0])
  const entityMetrics = sliceForTab[activeSubValue] || {}

  const entities = (data.entities || []).slice().sort((a, b) => (a.role === 'primary' ? -1 : b.role === 'primary' ? 1 : 0))

  return (
    <ReportSection id="analyst" eyebrow="ANALYST LAYER · SAME METRICS AS EVERY PAST CYCLE" title="The six core metrics, every slice" open={open} onToggle={onToggle}>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 18 }}>
        {TABS.map((t) => (
          <button
            key={t.key} type="button" onClick={() => { setTab(t.key); setSubValue(null) }}
            style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase',
              padding: '9px 14px', borderRadius: 999, cursor: 'pointer',
              border: `1px solid ${t.key === tab ? 'var(--ink)' : 'var(--border)'}`,
              background: t.key === tab ? 'var(--ink)' : 'var(--surface)',
              color: t.key === tab ? '#fff' : 'var(--muted)',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab !== 'overall' && subValues.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
          {subValues.map((v) => (
            <button
              key={v} type="button" onClick={() => setSubValue(v)}
              style={{
                fontSize: 11.5, padding: '5px 11px', borderRadius: 999, cursor: 'pointer',
                border: `1px solid ${v === activeSubValue ? 'var(--blue)' : 'var(--border)'}`,
                background: v === activeSubValue ? 'var(--blue-tint)' : 'var(--surface)',
                color: v === activeSubValue ? 'var(--blue-deep)' : 'var(--muted)',
              }}
            >
              {v}
            </button>
          ))}
        </div>
      )}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5, marginTop: 18 }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', padding: '10px', fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--faint)', fontWeight: 500 }}>Metric</th>
            {entities.map((e) => (
              <th key={e.code || e.name} style={{ textAlign: 'left', padding: '10px', fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: e.role === 'primary' ? 'var(--blue)' : 'var(--faint)', fontWeight: 500 }}>
                {e.name}{e.role === 'primary' ? ' (you)' : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRIC_ROWS.map((m) => (
            <tr key={m.key}>
              <td style={{ padding: '10px', borderTop: '1px solid var(--hairline)', fontWeight: 600, color: 'var(--text-strong)' }}>{m.label}</td>
              {entities.map((e) => {
                const metrics = entityMetrics[e.code]
                return (
                  <td key={e.code || e.name} className="num" style={{ padding: '10px', borderTop: '1px solid var(--hairline)', fontFamily: 'var(--font-mono)', color: e.role === 'primary' ? 'var(--text-strong)' : 'var(--muted)' }}>
                    {metrics ? fmt(metrics[m.key], m.suffix) : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </ReportSection>
  )
}
