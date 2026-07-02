import React, { useState, useEffect } from 'react'
import { api } from '../api.js'
import Sidebar from './Sidebar.jsx'
import ScopeSkuManager from './ScopeSkuManager.jsx'

// ─── Design tokens (verbatim from CycleDashboard.jsx) ────────────────────────
const T = {
  navy:        '#0D1829',
  navyMid:     '#162032',
  navyBdr:     '#1E2D42',
  white:       '#FFFFFF',
  offWhite:    '#F8FAFC',
  slate:       '#64748B',
  slateLight:  '#94A3B8',
  border:      '#E2E8F0',
  borderDark:  '#CBD5E1',
  text:        '#0F172A',
  textMid:     '#334155',
  teal:        '#0D9488',
  tealLight:   '#CCFBF1',
  indigo:      '#4F46E5',
  green:       '#16A34A',
  greenLight:  '#DCFCE7',
  amber:       '#D97706',
  amberLight:  '#FEF3C7',
  red:         '#DC2626',
  redLight:    '#FEE2E2',
  sidebarText: '#94A3B8',
}

// ─── Chart color palette ──────────────────────────────────────────────────────
const CHART_COLORS = [
  '#0F172A',  // M001 primary: near-black
  '#3B82F6',  // M002: blue
  '#6B7280',  // M003: grey
  '#F59E0B',  // M004: amber
  '#94A3B8',  // M005: light slate
  '#10B981',  // M006: teal
  '#EF4444',  // M007: red
  '#8B5CF6',  // M008: purple
]

// ─── Scorecard metric definitions ─────────────────────────────────────────────
const SCORECARD_METRICS = [
  { key: 'mention_rate',       label: 'Mention Rate'           },
  { key: 'som',                label: 'Share of Mentions'      },
  { key: 'rsi',                label: 'Recommendation Strength'},
  { key: 'position_index',     label: 'Position Index'         },
  { key: 'pdi',                label: 'Platform Distribution'  },
  { key: 'deal_citation_rate', label: 'Incentive Citation Rate'},
]

// ─── Helpers ──────────────────────────────────────────────────────────────────
function heatColor(value) {
  if (value >= 70) return '#16A34A'
  if (value >= 50) return '#D97706'
  if (value >= 30) return '#EA580C'
  return '#DC2626'
}

// RSI-specific heat color: raw scale −1 to +3
function heatColorRsi(value) {
  if (value === null || value === undefined) return T.slate
  if (value >= 1.5) return '#16A34A'
  if (value >= 0.5) return '#D97706'
  if (value >= 0.0) return '#EA580C'
  return '#DC2626'
}

function formatMetric(v) {
  if (v === null || v === undefined) return '—'
  if (v < 10) return v.toFixed(1).padStart(4, '0')
  return v.toFixed(1)
}

// RSI-specific formatter: 2 decimal places, sign preserved
function formatRsi(v) {
  if (v === null || v === undefined) return '—'
  return v.toFixed(2)
}

// Relative min-max normalisation across an array of values.
// Returns each value mapped to [0, 100] relative to the set's own min/max.
// All-equal values map to 50 (mid-point). Nulls pass through as null.
function relativeNormalize(values) {
  const valid = values.filter(v => v !== null && v !== undefined)
  if (valid.length === 0) return values.map(() => 50)
  const minV = Math.min(...valid)
  const maxV = Math.max(...valid)
  if (maxV === minV) return values.map(v => (v === null || v === undefined) ? null : 50)
  return values.map(v => {
    if (v === null || v === undefined) return null
    return Math.round(((v - minV) / (maxV - minV)) * 100)
  })
}

function abbrevName(name) {
  if (!name) return ''
  const words = name.trim().split(' ')
  if (words.length === 1) return words[0].toUpperCase()
  if (words[0].toLowerCase() === 'philips') return 'PHILIPS'
  return words[0].toUpperCase()
}

// Convert slices.overall into the metrics array format expected by chart components
function buildMetricsArray(overall) {
  if (!overall) return []
  const codes = Object.keys(overall)
  return SCORECARD_METRICS.map(m => ({
    key:    m.key,
    label:  m.label,
    values: Object.fromEntries(
      codes.map(c => [c, overall[c]?.[m.key] ?? 0])
    ),
  }))
}


// ─── Skeleton card ────────────────────────────────────────────────────────────
function SkeletonCard({ height = 240, delay = 0 }) {
  return (
    <div style={{
      background: T.white,
      border: `1px solid ${T.border}`,
      borderRadius: 12,
      height,
      animation: `mdPulse 1.5s ease-in-out ${delay}s infinite`,
    }} />
  )
}

// ─── Donut chart ──────────────────────────────────────────────────────────────
function DonutChart({ entities, metrics, activeEntities }) {
  if (activeEntities.length === 0 || metrics.length === 0) return <ChartEmptyState />

  const DONUT_SIZE    = 200
  const STROKE_WIDTH  = 32
  const R             = (DONUT_SIZE / 2) - STROKE_WIDTH
  const CIRCUMFERENCE = 2 * Math.PI * R

  const somMetric = metrics.find(m => m.key === 'som')
  const somValues = activeEntities.map(code => ({
    code,
    value:  somMetric?.values[code] || 0,
    entity: entities.find(e => e.code === code),
  }))
  const total = somValues.reduce((s, v) => s + v.value, 0) || 1

  let offset = 0
  const segments = somValues.map(item => {
    const dash = (item.value / total) * CIRCUMFERENCE
    const seg  = { ...item, dash, offset }
    offset += dash
    return seg
  })

  const primaryEntity = somValues[0]
  const primaryPct    = Math.round((primaryEntity?.value || 0) / total * 100)
  const cx = DONUT_SIZE / 2, cy = DONUT_SIZE / 2

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
      <div style={{ position: 'relative', width: DONUT_SIZE, height: DONUT_SIZE }}>
        <svg width={DONUT_SIZE} height={DONUT_SIZE}>
          <circle cx={cx} cy={cy} r={R} fill="none" stroke={T.border} strokeWidth={STROKE_WIDTH} />
          {segments.map(seg => (
            <circle
              key={seg.code}
              cx={cx} cy={cy} r={R}
              fill="none"
              stroke={seg.entity?.color || T.slate}
              strokeWidth={STROKE_WIDTH}
              strokeDasharray={`${seg.dash} ${CIRCUMFERENCE}`}
              strokeDashoffset={-seg.offset}
              transform={`rotate(-90, ${cx}, ${cy})`}
              style={{ transition: 'stroke-dasharray 0.6s ease' }}
            />
          ))}
        </svg>
        <div style={{
          position: 'absolute', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)', textAlign: 'center', pointerEvents: 'none',
        }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: T.text, lineHeight: 1.1 }}>{primaryPct}%</div>
          <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: T.slate, letterSpacing: '0.05em', marginTop: 2 }}>
            {primaryEntity?.entity ? abbrevName(primaryEntity.entity.name) : 'ORAL-B'}
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
        {somValues.map(item => (
          <div key={item.code} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: item.entity?.color || T.slate, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: T.textMid, flex: 1 }}>{item.entity?.name || item.code}</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: T.textMid, fontFamily: 'monospace' }}>
              {Math.round(item.value / total * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Horizontal bar chart ─────────────────────────────────────────────────────
function MentionRateChart({ entities, metrics, activeEntities }) {
  if (activeEntities.length === 0 || metrics.length === 0) return <ChartEmptyState />

  const [animated, setAnimated] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 80)
    return () => clearTimeout(t)
  }, [activeEntities])

  const mentionMetric = metrics.find(m => m.key === 'mention_rate')
  const rows = activeEntities.map((code, i) => ({
    code,
    entity: entities.find(e => e.code === code),
    value:  mentionMetric?.values[code] || 0,
    delay:  i * 0.1,
  }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {rows.map(row => (
        <div key={row.code}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', color: T.slate, letterSpacing: '0.05em' }}>
              {abbrevName(row.entity?.name || row.code)}
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, color: T.textMid, fontFamily: 'monospace' }}>
              {row.value.toFixed(1)}%
            </span>
          </div>
          <div style={{ height: 8, background: T.border, borderRadius: 4, overflow: 'hidden' }}>
            <div style={{
              height: '100%',
              width: animated ? `${row.value}%` : '0%',
              background: row.entity?.color || T.slate,
              borderRadius: 4,
              transition: `width 0.8s ease ${row.delay}s`,
            }} />
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Scatter chart ────────────────────────────────────────────────────────────
// Uses relative min-max normalisation so all active entities spread across the
// full plot area regardless of their absolute metric values.
// Tooltip preserves raw values (rawMr, rawRsi) for honest display.
function ScatterChart({ entities, overall, activeEntities }) {
  if (activeEntities.length === 0 || !overall || Object.keys(overall).length === 0) return <ChartEmptyState />

  const [animated, setAnimated] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 80)
    return () => clearTimeout(t)
  }, [activeEntities])

  const W = 420, H = 200
  const PAD = { top: 20, right: 20, bottom: 28, left: 32 }
  const chartW = W - PAD.left - PAD.right
  const chartH = H - PAD.top - PAD.bottom

  // Collect raw values for the active entity set only
  const rawMentionRates = activeEntities.map(code => overall?.[code]?.mention_rate ?? null)
  const rawRsiValues    = activeEntities.map(code => overall?.[code]?.rsi         ?? null)

  // Relative min-max: stretch values to fill 0–100 within this study's set
  const normMr  = relativeNormalize(rawMentionRates)
  const normRsi = relativeNormalize(rawRsiValues)

  const bubbles = activeEntities.map((code, i) => {
    const nx = normMr[i]  ?? 50
    const ny = normRsi[i] ?? 50
    const cx = PAD.left + (nx / 100) * chartW
    const cy = PAD.top  + chartH - (ny / 100) * chartH
    return {
      code, cx, cy,
      rawMr:  rawMentionRates[i],
      rawRsi: rawRsiValues[i],
      entity: entities.find(e => e.code === code),
      delay: i * 0.1,
    }
  })

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg width={W} height={H} style={{ display: 'block' }}>
        <line x1={PAD.left + chartW / 2} y1={PAD.top} x2={PAD.left + chartW / 2} y2={PAD.top + chartH} stroke={T.border} strokeWidth={1} strokeDasharray="4 4" />
        <line x1={PAD.left} y1={PAD.top + chartH / 2} x2={PAD.left + chartW} y2={PAD.top + chartH / 2} stroke={T.border} strokeWidth={1} strokeDasharray="4 4" />
        {[
          { text: 'NICHE LEADERS', x: PAD.left + 4,          y: PAD.top + 12 },
          { text: 'LEADERS',       x: PAD.left + chartW - 4, y: PAD.top + 12,          anchor: 'end' },
          { text: 'EMERGING',      x: PAD.left + 4,          y: PAD.top + chartH - 6 },
          { text: 'CHALLENGERS',   x: PAD.left + chartW - 4, y: PAD.top + chartH - 6,  anchor: 'end' },
        ].map(q => (
          <text key={q.text} x={q.x} y={q.y} fontSize={9} fontWeight={600} textAnchor={q.anchor || 'start'} fill={T.slateLight} fontFamily="sans-serif">
            {q.text}
          </text>
        ))}
        <text x={PAD.left + chartW / 2} y={H - 4} fontSize={10} fill={T.slate} textAnchor="middle" fontFamily="sans-serif">MENTION RATE (relative)</text>
        <text x={12} y={PAD.top + chartH / 2} fontSize={10} fill={T.slate} textAnchor="middle" fontFamily="sans-serif" transform={`rotate(-90, 12, ${PAD.top + chartH / 2})`}>RSI SCORE (relative)</text>
        {bubbles.map(b => (
          <g key={b.code}>
            <title>{b.entity?.name || b.code}{b.rawMr !== null ? ` · MR: ${b.rawMr?.toFixed(1)}%` : ''}{b.rawRsi !== null ? ` · RSI: ${b.rawRsi?.toFixed(2)}` : ''}</title>
            <circle cx={b.cx} cy={b.cy} r={18} fill={b.entity?.color || T.slate} stroke="white" strokeWidth={2}
              style={{ transform: animated ? 'scale(1)' : 'scale(0)', transformOrigin: `${b.cx}px ${b.cy}px`, transition: `transform 0.4s cubic-bezier(0.34,1.56,0.64,1) ${b.delay}s` }}
            />
            <text x={b.cx} y={b.cy - 22} fontSize={10} fill={T.textMid} textAnchor="middle" fontFamily="sans-serif">
              {abbrevName(b.entity?.name || b.code)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  )
}

// ─── Chart empty state ────────────────────────────────────────────────────────
const ChartEmptyState = () => (
  <div style={{
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '200px',
    color: T.slate,
    fontSize: '13px',
    border: '1px dashed ' + T.border,
    borderRadius: '8px',
    background: T.offWhite,
  }}>
    No data available for this cycle
  </div>
)

// ─── Position Index stacked bar ───────────────────────────────────────────────
function PositionIndexChart({ entities, positionData, activeEntities }) {
  const BAR_HEIGHT = 160
  const showCodes = activeEntities
    .filter(code => positionData != null && positionData[code] != null)
    .slice(0, 5)

  if (showCodes.length === 0) return <ChartEmptyState />

  const segments = [
    { key: 'top', label: 'TOP',              color: '#1E293B' },
    { key: 'mid', label: 'Position 2 and 3', color: '#64748B' },
    { key: 'low', label: '4+',               color: '#CBD5E1' },
  ]

  return (
    <div>
      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end', marginBottom: 12, justifyContent: 'center' }}>
        {showCodes.map(code => {
          const entity = entities.find(e => e.code === code)
          const data   = positionData[code]
          return (
            <div key={code} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 80, height: BAR_HEIGHT, display: 'flex', flexDirection: 'column', borderRadius: 6, overflow: 'hidden' }}>
                {segments.map(seg => (
                  <div key={seg.key} style={{ background: seg.color, height: `${data[seg.key]}%`, transition: 'height 0.6s ease' }} />
                ))}
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: T.slate, letterSpacing: '0.04em', textAlign: 'center' }}>
                {abbrevName(entity?.name || code)}
              </span>
              {data.mention_count != null && (
                <span style={{ fontSize: 9, color: T.slateLight, textAlign: 'center' }}>
                  {data.mention_count} mentions
                </span>
              )}
            </div>
          )
        })}
      </div>
      <div style={{ display: 'flex', gap: 16, justifyContent: 'center' }}>
        {segments.map(seg => (
          <div key={seg.key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 10, height: 10, background: seg.color, borderRadius: 2 }} />
            <span style={{ fontSize: 11, color: T.textMid }}>{seg.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Chart card wrapper ───────────────────────────────────────────────────────
function ChartCard({ title, children }) {
  return (
    <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20, position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: T.text }}>{title}</span>
        <button style={{ border: 'none', background: 'transparent', color: T.slate, fontSize: 18, cursor: 'pointer', padding: '0 4px' }}>···</button>
      </div>
      {children}
    </div>
  )
}

// ─── Slice sub-table ──────────────────────────────────────────────────────────
function SliceTable({ sliceData, entities, activeEntities, sliceLabel }) {
  const dimValues = Object.keys(sliceData || {}).sort()
  if (!dimValues.length) return (
    <div style={{ padding: 32, textAlign: 'center', color: T.slate, fontSize: 14 }}>No data for this slice.</div>
  )
  return (
    <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, overflow: 'hidden' }}>
      <div style={{ padding: '16px 20px', borderBottom: `1px solid ${T.border}` }}>
        <span style={{ fontSize: 16, fontWeight: 700, color: T.text }}>{sliceLabel} Breakdown</span>
      </div>
      {dimValues.map(dim => {
        const entityMetrics = sliceData[dim] || {}
        return (
          <div key={dim}>
            <div style={{ padding: '10px 20px', background: T.offWhite, borderBottom: `1px solid ${T.border}`, fontSize: 12, fontWeight: 700, textTransform: 'uppercase', color: T.slate, letterSpacing: '0.05em' }}>
              {dim}
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {SCORECARD_METRICS.map((metric, mi) => (
                  <tr key={metric.key} style={{ height: 40, borderBottom: mi < SCORECARD_METRICS.length - 1 ? `1px solid ${T.border}` : 'none' }}>
                    <td style={{ padding: '0 20px', width: 220, fontSize: 12, fontWeight: 600, color: T.textMid }}>{metric.label}</td>
                    {activeEntities.map(code => {
                      const v = entityMetrics[code]?.[metric.key] ?? null
                      return (
                        <td key={code} style={{ textAlign: 'center' }}>
                          {v !== null
                            ? <span style={{ fontSize: 13, fontWeight: 700, fontFamily: 'monospace', color: heatColor(v) }}>{formatMetric(v)}</span>
                            : <span style={{ fontSize: 13, color: T.slateLight }}>—</span>
                          }
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      })}
    </div>
  )
}

// ─── Truecost grid (SKU x retailer x tier) ────────────────────────────────────
// Renders the read-only results grid for cycle_mode='truecost' cycles, backed
// by GET /api/cycles/{code}/truecost-snapshots. One row per scope SKU, one
// column-group per swept tier.
export function TruecostGrid({ cycleCode, cycleData, onRunSweep, running }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [expanded, setExpanded] = useState(null) // `${scope_sku_id}:${tier}` of the open deals popover

  const load = () =>
    api.getCycleTruecostSnapshots(cycleCode)
      .then(res => { setData(res); setError(null) })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))

  useEffect(() => {
    setLoading(true)
    load()
    // Poll while the sweep is still running so the grid fills in live.
    if (cycleData?.status === 'running' || cycleData?.status === 'planned') {
      const id = setInterval(load, 10_000)
      return () => clearInterval(id)
    }
  }, [cycleCode, cycleData?.status])

  const tierKey = (t) => t.user_tier_name == null ? '__baseline__' : t.user_tier_name
  const tierLabel = (name) => name == null ? 'Non-member (baseline)' : name

  // Union of every tier name swept across all SKUs, baseline first, so the
  // grid has consistent columns even if a SKU is missing a tier (e.g. it's
  // still in progress, or unavailable for that tier only).
  const allTierKeys = []
  ;(data?.skus || []).forEach(sku => sku.tiers.forEach(t => {
    const k = tierKey(t)
    if (!allTierKeys.includes(k)) allTierKeys.push(k)
  }))
  allTierKeys.sort((a, b) => (a === '__baseline__' ? -1 : b === '__baseline__' ? 1 : 0))

  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <SkeletonCard height={48} delay={0} />
        <SkeletonCard height={48} delay={0.1} />
        <SkeletonCard height={48} delay={0.2} />
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, padding: '64px 32px', textAlign: 'center' }}>
        <p style={{ margin: 0, fontSize: 14, color: T.red }}>Could not load truecost results: {error}</p>
      </div>
    )
  }

  const skus = data?.skus || []
  const isPlanned = cycleData?.status === 'planned'
  const isRunning = cycleData?.status === 'running'

  if (skus.length === 0) {
    return (
      <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, padding: '64px 32px', textAlign: 'center' }}>
        <div style={{ fontSize: 32, marginBottom: 16 }}>{isPlanned ? '◷' : '📊'}</div>
        <h3 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 700, color: T.text }}>
          {isPlanned ? 'Sweep not started yet' : isRunning ? 'Sweep in progress…' : 'No results yet'}
        </h3>
        <p style={{ margin: '0 auto 20px', fontSize: 14, color: T.slate, maxWidth: 420 }}>
          {isPlanned
            ? 'The pipeline worker will sweep each selected brand\'s Measured SKUs through the Deal Engine within 30 seconds, or trigger it now.'
            : 'Results will appear here as each SKU is scraped and priced.'}
        </p>
        {isPlanned && (
          <button
            onClick={onRunSweep}
            disabled={running}
            style={{
              padding: '10px 24px', background: T.navy, color: T.white, border: 'none',
              borderRadius: 8, fontWeight: 700, fontSize: 14,
              cursor: running ? 'not-allowed' : 'pointer', opacity: running ? 0.7 : 1,
            }}
          >
            {running ? 'Starting…' : '▶ Run Sweep Now'}
          </button>
        )}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {(isPlanned || isRunning) && (
        <div style={{ background: T.offWhite, border: `1px solid ${T.border}`, borderRadius: 10, padding: '10px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13, color: T.textMid }}>
          <span>◷ {isRunning ? 'Sweep in progress — this grid updates automatically.' : 'Sweep queued.'}</span>
          {isPlanned && (
            <button onClick={onRunSweep} disabled={running}
              style={{ padding: '6px 14px', background: T.navy, color: T.white, border: 'none', borderRadius: 6, fontWeight: 600, fontSize: 12, cursor: running ? 'not-allowed' : 'pointer', opacity: running ? 0.7 : 1 }}>
              {running ? 'Starting…' : '▶ Run Sweep Now'}
            </button>
          )}
        </div>
      )}

      <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, overflow: 'hidden', overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: T.offWhite }}>
              <th style={{ padding: '10px 16px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: T.slate, borderBottom: `1px solid ${T.border}`, whiteSpace: 'nowrap' }}>SKU</th>
              <th style={{ padding: '10px 16px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: T.slate, borderBottom: `1px solid ${T.border}`, whiteSpace: 'nowrap' }}>Retailer</th>
              {allTierKeys.map(k => (
                <th key={k} colSpan={allTierKeys.length > 1 && k !== '__baseline__' ? 4 : 3}
                  style={{ padding: '10px 16px', textAlign: 'center', fontSize: 11, fontWeight: 700, color: T.slate, borderBottom: `1px solid ${T.border}`, borderLeft: `1px solid ${T.border}`, whiteSpace: 'nowrap' }}>
                  {tierLabel(k === '__baseline__' ? null : k)}
                </th>
              ))}
            </tr>
            <tr style={{ background: T.offWhite }}>
              <th style={{ borderBottom: `1px solid ${T.border}` }} />
              <th style={{ borderBottom: `1px solid ${T.border}` }} />
              {allTierKeys.map(k => (
                <React.Fragment key={k}>
                  <th style={{ padding: '6px 10px', textAlign: 'right', fontSize: 10, fontWeight: 600, color: T.slateLight, borderBottom: `1px solid ${T.border}`, borderLeft: `1px solid ${T.border}` }}>Listed</th>
                  <th style={{ padding: '6px 10px', textAlign: 'right', fontSize: 10, fontWeight: 600, color: T.slateLight, borderBottom: `1px solid ${T.border}` }}>True Cost</th>
                  <th style={{ padding: '6px 10px', textAlign: 'right', fontSize: 10, fontWeight: 600, color: T.slateLight, borderBottom: `1px solid ${T.border}` }}>Savings</th>
                  {allTierKeys.length > 1 && k !== '__baseline__' && (
                    <th style={{ padding: '6px 10px', textAlign: 'right', fontSize: 10, fontWeight: 600, color: T.slateLight, borderBottom: `1px solid ${T.border}` }}>Δ vs baseline</th>
                  )}
                </React.Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {skus.map(sku => {
              const tiersByKey = Object.fromEntries(sku.tiers.map(t => [tierKey(t), t]))
              return (
                <tr key={sku.scope_sku_id} style={{ borderBottom: `1px solid ${T.border}` }}>
                  <td style={{ padding: '10px 16px', fontWeight: 600 }}>
                    {sku.display_name || sku.brand || `SKU ${sku.scope_sku_id}`}
                  </td>
                  <td style={{ padding: '10px 16px', color: T.slate, fontFamily: 'monospace', fontSize: 12 }}>
                    {sku.merchant_slug || '—'}
                  </td>
                  {allTierKeys.map(k => {
                    const t = tiersByKey[k]
                    const cellKey = `${sku.scope_sku_id}:${k}`
                    if (!t) {
                      return (
                        <React.Fragment key={k}>
                          <td colSpan={allTierKeys.length > 1 && k !== '__baseline__' ? 4 : 3}
                            style={{ padding: '10px 16px', textAlign: 'center', color: T.slateLight, borderLeft: `1px solid ${T.border}` }}>
                            pending
                          </td>
                        </React.Fragment>
                      )
                    }
                    if (t.status === 'ground_truth_unavailable') {
                      return (
                        <React.Fragment key={k}>
                          <td colSpan={allTierKeys.length > 1 && k !== '__baseline__' ? 4 : 3}
                            style={{ padding: '10px 16px', textAlign: 'center', borderLeft: `1px solid ${T.border}` }}
                            title={t.error_message || 'Deal Engine unavailable for this SKU/tier'}
                          >
                            <span style={{ padding: '3px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700, color: '#991B1B', background: '#FEE2E2' }}>
                              ⚠ Unavailable
                            </span>
                          </td>
                        </React.Fragment>
                      )
                    }
                    const delta = sku.member_vs_baseline_delta?.[k]
                    return (
                      <React.Fragment key={k}>
                        <td style={{ padding: '10px 10px', textAlign: 'right', borderLeft: `1px solid ${T.border}` }}>
                          {t.listed_price != null ? `$${t.listed_price.toFixed(2)}` : '—'}
                          {t.price_was_refreshed && <span title="Price freshly scraped for this sweep" style={{ marginLeft: 4, fontSize: 10, color: T.teal }}>●</span>}
                        </td>
                        <td style={{ padding: '10px 10px', textAlign: 'right', fontWeight: 700 }}>
                          {t.true_cost != null ? `$${t.true_cost.toFixed(2)}` : '—'}
                        </td>
                        <td style={{ padding: '10px 10px', textAlign: 'right' }}>
                          <span
                            onMouseEnter={() => setExpanded(cellKey)}
                            onMouseLeave={() => setExpanded(null)}
                            style={{ position: 'relative', cursor: (t.applied_deals || []).length > 0 ? 'help' : 'default', color: t.total_savings > 0 ? T.green : T.slate }}
                          >
                            {t.total_savings != null ? `$${t.total_savings.toFixed(2)}` : '$0.00'}
                            {(t.applied_deals || []).length > 0 && ' ⓘ'}
                            {expanded === cellKey && (t.applied_deals || []).length > 0 && (
                              <div style={{
                                position: 'absolute', right: 0, top: '100%', zIndex: 10,
                                background: T.navy, color: T.white, borderRadius: 8, padding: '10px 12px',
                                fontSize: 11, fontWeight: 400, textAlign: 'left', width: 220, marginTop: 4,
                                boxShadow: '0 8px 20px rgba(0,0,0,0.25)',
                              }}>
                                {t.applied_deals.map((d, i) => (
                                  <div key={i} style={{ marginBottom: i < t.applied_deals.length - 1 ? 4 : 0 }}>
                                    {d.title || d.deal_type || JSON.stringify(d)}
                                  </div>
                                ))}
                              </div>
                            )}
                          </span>
                        </td>
                        {allTierKeys.length > 1 && k !== '__baseline__' && (
                          <td style={{ padding: '10px 10px', textAlign: 'right', fontWeight: 600, color: delta == null ? T.slateLight : delta > 0 ? T.green : delta < 0 ? T.red : T.slate }}>
                            {delta == null ? '—' : `${delta > 0 ? '+' : ''}$${delta.toFixed(2)}`}
                          </td>
                        )}
                      </React.Fragment>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function MetricsDashboard({ cycleCode, onNavigate, onViewResponses, onViewActions }) {
  const [cycleData,      setCycleData]      = useState(null)
  const [metricsData,    setMetricsData]    = useState(null)
  const [entities,       setEntities]       = useState([])
  const [loading,        setLoading]        = useState(true)
  const [activeSlice,    setActiveSlice]    = useState('overall')
  const [activeEntities, setActiveEntities] = useState([])
  const [allCycles,      setAllCycles]      = useState([])
  const [positionData,   setPositionData]   = useState(null)
  const [showScope,      setShowScope]      = useState(false)
  const [runningSweep,   setRunningSweep]   = useState(false)

  // ── Data loading ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!cycleCode) {
      setEntities([])
      setActiveEntities([])
      setMetricsData(null)
      setPositionData(null)
      setLoading(false)
      return
    }

    setLoading(true)

    Promise.allSettled([
      api.getCycleEntities(cycleCode),
      api.getMetrics(cycleCode),
      api.getCycle(cycleCode),
      api.getCycles(),
      api.getPositions(cycleCode),
    ]).then(([entResult, metResult, cycResult, cyclesResult, posResult]) => {

      // Determine entity list from live API
      let liveEntities = null
      if (entResult.status === 'fulfilled' && entResult.value?.entities?.length > 0) {
        liveEntities = entResult.value.entities
      }

      // Determine metrics (slices) from live API
      let liveMetrics = null
      if (metResult.status === 'fulfilled' && metResult.value?.slices) {
        liveMetrics = metResult.value
      }

      // Cycle metadata
      if (cycResult.status === 'fulfilled') {
        setCycleData(cycResult.value)
      }

      // All cycles for selector
      if (cyclesResult.status === 'fulfilled' && Array.isArray(cyclesResult.value)) {
        setAllCycles(cyclesResult.value)
      }

      // Position data
      if (
        posResult.status === 'fulfilled' &&
        posResult.value?.positions &&
        Object.keys(posResult.value.positions).length > 0
      ) {
        setPositionData(posResult.value.positions)
      } else {
        setPositionData(null)
      }

      if (liveMetrics && liveEntities) {
        // Assign CHART_COLORS by position
        const palette = liveEntities.map((e, i) => ({
          ...e,
          color: CHART_COLORS[i % CHART_COLORS.length],
        }))
        setEntities(palette)
        setActiveEntities(palette.map(e => e.code))
        setMetricsData(liveMetrics)
      } else {
        // Cycle exists but has no data yet
        setEntities([])
        setActiveEntities([])
        setMetricsData(null)
        console.error('Failed to load metrics data for cycle:', cycleCode)
      }

      setLoading(false)
    })
  }, [cycleCode])

  // ── Entity toggle ───────────────────────────────────────────────────────────
  function toggleEntity(code) {
    setActiveEntities(prev => {
      if (prev.includes(code)) {
        if (prev.length === 1) return prev
        return prev.filter(c => c !== code)
      }
      return [...prev, code]
    })
  }

  // ── Derived data ────────────────────────────────────────────────────────────
  const slices = metricsData?.slices || {}

  // Build metrics array for chart components from slices.overall
  const metrics = buildMetricsArray(slices.overall)

  // Available slice keys (determines which tabs are enabled)
  const availableSliceKeys = Object.keys(slices)

  const SLICES = [
    { key: 'overall',       label: 'Overall'     },
    { key: 'by_stage',      label: 'By Stage'    },
    { key: 'by_category',   label: 'By Category' },
    { key: 'by_platform',   label: 'By Platform' },
    { key: 'by_persona',    label: 'By Persona'  },
    { key: 'by_topic',      label: 'By Topic'    },
  ]

  const displayCode = cycleCode || '—'
  const isTruecost = cycleData?.cycle_mode === 'truecost'

  // ── Run sweep — reuses the existing resume-cycle trigger (sets status
  // back to 'planned' so the pipeline worker's existing cycle_mode branch
  // picks it up within 30s; no new run path is introduced here). ──────────
  async function handleRunSweep() {
    if (!cycleCode) return
    setRunningSweep(true)
    try {
      await api.resumeCycle(cycleCode)
      setCycleData(c => c ? { ...c, status: 'planned' } : c)
    } catch (err) {
      console.error('Could not start sweep:', err.message)
      alert(`Could not start sweep: ${err.message}`)
    } finally {
      setRunningSweep(false)
    }
  }

  // ─── RENDER ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", background: T.offWhite }}>
      <style>{`
        @keyframes mdPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        * { box-sizing: border-box; }
        .md-tab-hover:hover { color: ${T.textMid} !important; }
        .md-entity-pill:hover { opacity: 0.85; }
        .md-breadcrumb-link:hover { color: ${T.textMid} !important; }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>

      <Sidebar activeView="dashboard" onNavigate={onNavigate} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh', overflow: 'hidden', marginLeft: 200 }}>

        {/* ── Topbar ──────────────────────────────────────────────────────── */}
        <div style={{
          height: 56, background: T.white, borderBottom: `1px solid ${T.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 28px', flexShrink: 0,
        }}>
          <div style={{ fontSize: 13, color: T.slate, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="md-breadcrumb-link" onClick={() => onNavigate && onNavigate('dashboard')}
              style={{ color: T.slate, cursor: 'pointer', transition: 'color 0.1s' }}>Cycles</span>
            <span style={{ color: T.slateLight, margin: '0 2px' }}>›</span>
            <span className="md-breadcrumb-link" onClick={() => onNavigate && onNavigate('dashboard')}
              style={{ color: T.textMid, cursor: 'pointer', transition: 'color 0.1s', fontFamily: 'monospace', fontSize: 12 }}>
              {displayCode}
            </span>
            <span style={{ color: T.slateLight, margin: '0 2px' }}>›</span>
            <span style={{ color: T.text, fontWeight: 700 }}>Metrics</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <button
              onClick={onViewResponses}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '8px 16px', borderRadius: '8px',
                border: `1px solid ${T.border}`, background: T.white,
                color: T.text, fontSize: '13px', fontWeight: '600',
                cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              ⊙ View Responses
            </button>
            <button
              onClick={onViewActions}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '8px 16px', borderRadius: '8px',
                border: `1px solid ${T.border}`, background: T.white,
                color: T.text, fontSize: '13px', fontWeight: '600',
                cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              ⚡ View Actions
            </button>
            <div style={{ position: 'relative' }}>
              <select
                value={displayCode}
                onChange={e => onNavigate && onNavigate('metrics', { cycleCode: e.target.value })}
                style={{
                  background: T.navy, color: T.white, border: 'none', borderRadius: 8,
                  padding: '8px 28px 8px 14px', fontSize: 13, fontWeight: 600,
                  cursor: 'pointer', appearance: 'none', outline: 'none',
                }}
              >
                {allCycles.length > 0
                  ? allCycles.map(c => <option key={c.cycle_code} value={c.cycle_code}>Cycle: {c.cycle_code}</option>)
                  : <option value={displayCode}>Cycle: {displayCode}</option>
                }
              </select>
              <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', color: T.sidebarText, fontSize: 10, pointerEvents: 'none' }}>▾</span>
            </div>
            <span style={{ fontSize: 18, cursor: 'pointer' }}>🔔</span>
            <div style={{ width: 32, height: 32, borderRadius: '50%', background: T.indigo, color: T.white, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700 }}>E</div>
          </div>
        </div>

        {/* ── Entity filter row (query cycles only) ────────────────────────── */}
        {!isTruecost && (
          <div style={{
            background: T.white, borderBottom: `1px solid ${T.border}`,
            padding: '12px 28px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', flexShrink: 0,
          }}>
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.slate, marginRight: 4 }}>
              ENTITIES
            </span>
            {entities.map(entity => {
              const isActive = activeEntities.includes(entity.code)
              return (
                <button
                  key={entity.code}
                  className="md-entity-pill"
                  onClick={() => toggleEntity(entity.code)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '6px 14px', borderRadius: 20,
                    border: isActive ? 'none' : `1px solid ${T.border}`,
                    background: isActive ? T.navy : T.white,
                    color: isActive ? T.white : T.textMid,
                    fontSize: 13, fontWeight: 600, cursor: 'pointer', transition: 'all 0.12s',
                  }}
                >
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: isActive ? entity.color : T.slateLight, flexShrink: 0 }} />
                  {entity.name}
                  <span style={{ fontSize: 10 }}>▾</span>
                </button>
              )
            })}
          </div>
        )}

        {/* ── Slice tabs (query cycles only) ───────────────────────────────── */}
        {!isTruecost && (
          <div style={{
            background: T.white, borderBottom: `1px solid ${T.border}`,
            padding: '0 28px', display: 'flex', alignItems: 'center', flexShrink: 0,
          }}>
            {SLICES.map(slice => {
              const isActive  = activeSlice === slice.key
              const isEnabled = slice.key === 'overall' || availableSliceKeys.includes(slice.key)
              return (
                <div
                  key={slice.key}
                  className="md-tab-hover"
                  title={!isEnabled ? 'Coming soon' : undefined}
                  onClick={() => setActiveSlice(slice.key)}
                  style={{
                    padding: '14px 4px', marginRight: 28,
                    fontSize: 14,
                    fontWeight: isActive ? 700 : 500,
                    color: isActive ? T.text : T.slate,
                    borderBottom: isActive ? `2px solid ${T.text}` : '2px solid transparent',
                    marginBottom: -1, cursor: 'pointer',
                    opacity: !isEnabled ? 0.45 : 1,
                    transition: 'color 0.1s', userSelect: 'none', whiteSpace: 'nowrap',
                  }}
                >
                  {slice.label}
                  {isEnabled && slice.key !== 'overall' && (
                    <span style={{ marginLeft: 4, fontSize: 10, fontWeight: 600, color: T.teal }}>✓</span>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* ── Content area ─────────────────────────────────────────────────── */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px', background: T.offWhite }}>

          {/* Scope section — this cycle's effective SKU-level scope.
              Editable while Planned and not yet frozen; read-only once a
              run has started (scope_frozen_at set). */}
          {cycleData?.id != null && (
            <div style={{ marginBottom: 20 }}>
              <button
                onClick={() => setShowScope(v => !v)}
                style={{
                  padding: '7px 14px', background: T.white, border: `1px solid ${T.border}`,
                  color: T.textMid, borderRadius: 8, fontWeight: 600, fontSize: 12, cursor: 'pointer',
                }}
              >
                {showScope ? 'Hide Scope' : 'Scope'}
              </button>
              {showScope && (
                <ScopeSkuManager
                  cycleId={cycleData.id}
                  readOnly={cycleData.status !== 'planned'}
                />
              )}
            </div>
          )}

          {/* Truecost cycles: SKU x retailer x tier results grid instead of
              the query pipeline's entity/metrics/charts below. */}
          {isTruecost && cycleCode && (
            <TruecostGrid cycleCode={cycleCode} cycleData={cycleData} onRunSweep={handleRunSweep} running={runningSweep} />
          )}

          {/* Page-level empty state (query cycles only) */}
          {!isTruecost && !loading && entities.length === 0 && (
            <div style={{ textAlign: 'center', padding: '60px 20px' }}>
              <div style={{ fontWeight: '600', fontSize: '15px', color: T.textMid, marginBottom: '8px' }}>
                No data for this cycle yet
              </div>
              <div style={{ fontSize: '13px', color: T.slate }}>
                Run the cycle to start collecting metrics.
              </div>
            </div>
          )}

          {/* Non-overall slices */}
          {!loading && entities.length > 0 && activeSlice !== 'overall' && (
            (() => {
              const currentSlice = SLICES.find(s => s.key === activeSlice)
              const isEnabled    = availableSliceKeys.includes(activeSlice)
              if (!isEnabled) {
                return (
                  <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, padding: '64px 32px', textAlign: 'center' }}>
                    <div style={{ fontSize: 32, marginBottom: 16 }}>📊</div>
                    <h3 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 700, color: T.text }}>
                      {currentSlice?.label} slice coming soon
                    </h3>
                    <p style={{ margin: '0 auto', fontSize: 14, color: T.slate, maxWidth: 420 }}>
                      Run more cycles to unlock dimensional breakdowns.
                    </p>
                  </div>
                )
              }
              return (
                <>
                  {/* Entity column headers for slice table */}
                  <SliceTable
                    sliceData={slices[activeSlice]}
                    entities={entities}
                    activeEntities={activeEntities}
                    sliceLabel={currentSlice?.label || activeSlice}
                  />
                </>
              )
            })()
          )}

          {!loading && entities.length > 0 && activeSlice === 'overall' && (
            <>
              {/* Loading skeletons */}
              {loading && (
                <>
                  <SkeletonCard height={280} delay={0} />
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginTop: 20 }}>
                    <SkeletonCard height={240} delay={0.1} />
                    <SkeletonCard height={240} delay={0.2} />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginTop: 20 }}>
                    <SkeletonCard height={240} delay={0.3} />
                    <SkeletonCard height={240} delay={0.4} />
                  </div>
                </>
              )}

              {!loading && (
                <>
                  {/* ── SECTION 1: Summary Scorecard ──────────────────────── */}
                  <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, overflow: 'hidden', marginBottom: 20 }}>
                    <div style={{ padding: '16px 20px', borderBottom: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: 16, fontWeight: 700, color: T.text }}>Summary Scorecard</span>
                      <span style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.slate }}>
                        Scores 0–100 · RSI raw (−1 to +3)
                      </span>
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ background: T.offWhite, height: 36, borderBottom: `1px solid ${T.border}` }}>
                          <th style={{ padding: '0 20px', width: 220, textAlign: 'left', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: T.slate, letterSpacing: '0.05em' }}>METRIC</th>
                          {activeEntities.map(code => {
                            const e = entities.find(en => en.code === code)
                            return (
                              <th key={code} style={{ textAlign: 'center', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: T.slate, letterSpacing: '0.05em' }}>
                                {abbrevName(e?.name || code)}
                              </th>
                            )
                          })}
                        </tr>
                      </thead>
                      <tbody>
                        {SCORECARD_METRICS.map((metric, mi) => (
                          <tr key={metric.key} style={{ height: 44, borderBottom: mi < SCORECARD_METRICS.length - 1 ? `1px solid ${T.border}` : 'none' }}>
                            <td style={{ padding: '0 20px', fontSize: 13, fontWeight: 600, color: T.text }}>
                              {metric.key === 'rsi' ? (
                                <span>
                                  {metric.label}
                                  <span style={{ display: 'block', fontSize: 9, fontStyle: 'italic', color: T.slateLight, fontWeight: 400 }}>
                                    −1 to +3
                                  </span>
                                </span>
                              ) : metric.label}
                            </td>
                            {activeEntities.map(code => {
                              const v = slices.overall?.[code]?.[metric.key] ?? null
                              const isRsi = metric.key === 'rsi'
                              return (
                                <td key={code} style={{ textAlign: 'center' }}>
                                  {v !== null
                                    ? <span style={{ fontSize: 14, fontWeight: 700, fontFamily: 'monospace', color: isRsi ? heatColorRsi(v) : heatColor(v) }}>
                                        {isRsi ? formatRsi(v) : formatMetric(v)}
                                      </span>
                                    : <span style={{ fontSize: 14, color: T.slateLight }}>—</span>
                                  }
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* ── SECTION 2: Chart row 1 ─────────────────────────────── */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
                    <ChartCard title="Share of Mentions (SoM%)">
                      <DonutChart entities={entities} metrics={metrics} activeEntities={activeEntities} />
                    </ChartCard>
                    <ChartCard title="Mention Rate (%)">
                      <MentionRateChart entities={entities} metrics={metrics} activeEntities={activeEntities} />
                    </ChartCard>
                  </div>

                  {/* ── SECTION 3: Chart row 2 ─────────────────────────────── */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                    <div>
                      <ChartCard title="Recommendation Strength vs Mention Rate">
                        <ScatterChart entities={entities} overall={slices.overall} activeEntities={activeEntities} />
                      </ChartCard>
                      <p style={{ margin: '8px 0 0', fontSize: 11, color: T.slateLight, fontStyle: 'italic' }}>
                        Axes show relative performance within this study. Quadrant dividers are at the study midpoint on each dimension.
                      </p>
                    </div>
                    <ChartCard title="Position Index by Quintile">
                      <PositionIndexChart entities={entities} positionData={positionData} activeEntities={activeEntities} />
                    </ChartCard>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
