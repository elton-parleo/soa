import React, { useState, useEffect, useRef } from 'react'
import { api } from '../api.js'

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

// ─── Mock data ────────────────────────────────────────────────────────────────
const buildMockData = (cycleCode) => {
  const entities = [
    { code: 'M001', name: 'Oral-B',          color: '#0F172A' },
    { code: 'M002', name: 'Philips Sonicare', color: '#3B82F6' },
    { code: 'M003', name: 'Colgate',          color: '#6B7280' },
    { code: 'M004', name: 'Sensodyne',        color: '#F59E0B' },
    { code: 'M005', name: 'Other',            color: '#94A3B8' },
  ]

  const metrics = [
    {
      key:    'mention_rate',
      label:  'Mention Rate',
      values: { M001: 74.2, M002: 58.1, M003: 42.3, M004: 29.8, M005: 15.6 },
    },
    {
      key:    'som',
      label:  'Share of Mentions',
      values: { M001: 88.4, M002: 72.9, M003: 55.2, M004: 48.1, M005: 21.0 },
    },
    {
      key:    'rsi',
      label:  'Recommendation Strength',
      values: { M001: 62.1, M002: 76.4, M003: 34.2, M004: 52.8, M005: 12.5 },
    },
    {
      key:    'position_index',
      label:  'Position Index',
      values: { M001: 81.5, M002: 64.2, M003: 70.1, M004: 59.3, M005: 44.8 },
    },
    {
      key:    'pdi',
      label:  'Platform Distribution',
      values: { M001: 92.0, M002: 45.5, M003: 61.2, M004: 31.4, M005: 8.2 },
    },
    {
      key:    'deal_citation',
      label:  'Incentive Citation Rate',
      values: { M001: 8.2,  M002: 12.4, M003: 5.1,  M004: 3.8,  M005: 2.2 },
    },
  ]

  const positionData = {
    M001: { top: 55, mid: 30, low: 15 },
    M002: { top: 38, mid: 42, low: 20 },
    M003: { top: 45, mid: 35, low: 20 },
  }

  return { entities, metrics, positionData }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function heatColor(value) {
  if (value >= 70) return '#16A34A'
  if (value >= 50) return '#D97706'
  if (value >= 30) return '#EA580C'
  return '#DC2626'
}

function formatMetric(v) {
  if (v < 10) return v.toFixed(1).padStart(4, '0')
  return v.toFixed(1)
}

function abbrevName(name) {
  if (!name) return ''
  const words = name.trim().split(' ')
  if (words.length === 1) return words[0].toUpperCase()
  // Shorten compound names
  if (words[0].toLowerCase() === 'philips') return 'PHILIPS'
  return words[0].toUpperCase()
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ onNavigate }) {
  const navItems = [
    { label: 'Cycles',          view: 'dashboard', active: true  },
    { label: 'Studies',         view: 'studies',   active: false },
    { label: 'Results',         view: 'results',   active: false },
    { label: 'Entity Registry', view: 'entities',  active: false },
    { label: 'Settings',        view: 'settings',  active: false },
  ]
  return (
    <div style={{ width: 200, minHeight: '100vh', background: T.navy, display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
      <div style={{ padding: '24px 20px 16px' }}>
        <div style={{ color: T.white, fontWeight: 700, fontSize: 15 }}>SoA Platform</div>
        <div style={{ color: T.sidebarText, fontSize: 11, marginTop: 2 }}>Brand Intelligence</div>
      </div>
      <nav style={{ flex: 1, padding: '8px 0' }}>
        {navItems.map(item => (
          <div
            key={item.label}
            onClick={() => onNavigate && onNavigate(item.view)}
            style={{
              padding: '10px 20px',
              fontSize: 13,
              fontWeight: item.active ? 600 : 400,
              color: item.active ? T.white : T.sidebarText,
              background: item.active ? T.navyMid : 'transparent',
              borderLeft: item.active ? `3px solid ${T.teal}` : '3px solid transparent',
              cursor: 'pointer',
            }}
          >
            {item.label}
          </div>
        ))}
      </nav>
      <div style={{ padding: '16px 20px', borderTop: `1px solid ${T.navyBdr}` }}>
        <div style={{ fontSize: 12, color: T.sidebarText, cursor: 'pointer', marginBottom: 8 }}>Help Center</div>
        <div style={{ fontSize: 12, color: T.sidebarText, cursor: 'pointer' }}>Log Out</div>
      </div>
    </div>
  )
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
  const DONUT_SIZE   = 200
  const STROKE_WIDTH = 32
  const R            = (DONUT_SIZE / 2) - STROKE_WIDTH
  const CIRCUMFERENCE = 2 * Math.PI * R

  const somMetric = metrics.find(m => m.key === 'som')
  const somValues = activeEntities.map(code => ({
    code,
    value:  somMetric?.values[code] || 0,
    entity: entities.find(e => e.code === code),
  }))
  const total = somValues.reduce((s, v) => s + v.value, 0) || 1

  // Build segments
  let offset = 0
  const segments = somValues.map(item => {
    const pct    = item.value / total
    const dash   = pct * CIRCUMFERENCE
    const seg    = { ...item, dash, offset }
    offset += dash
    return seg
  })

  const primaryEntity = somValues[0]
  const primaryPct    = total > 0
    ? Math.round((primaryEntity?.value || 0) / total * 100)
    : 0

  const cx = DONUT_SIZE / 2
  const cy = DONUT_SIZE / 2

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
      <div style={{ position: 'relative', width: DONUT_SIZE, height: DONUT_SIZE }}>
        <svg width={DONUT_SIZE} height={DONUT_SIZE}>
          {/* Background ring */}
          <circle
            cx={cx} cy={cy} r={R}
            fill="none"
            stroke={T.border}
            strokeWidth={STROKE_WIDTH}
          />
          {segments.map((seg, i) => (
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
        {/* Center label */}
        <div style={{
          position: 'absolute', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          textAlign: 'center',
          pointerEvents: 'none',
        }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: T.text, lineHeight: 1.1 }}>
            {primaryPct}%
          </div>
          <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: T.slate, letterSpacing: '0.05em', marginTop: 2 }}>
            {primaryEntity?.entity ? abbrevName(primaryEntity.entity.name) : 'ORAL-B'}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
        {somValues.map(item => (
          <div key={item.code} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: item.entity?.color || T.slate, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: T.textMid, flex: 1 }}>{item.entity?.name || item.code}</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: T.textMid, fontFamily: 'monospace' }}>
              {total > 0 ? Math.round(item.value / total * 100) : 0}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Horizontal bar chart ─────────────────────────────────────────────────────
function MentionRateChart({ entities, metrics, activeEntities }) {
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
function ScatterChart({ entities, metrics, activeEntities }) {
  const [animated, setAnimated] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 80)
    return () => clearTimeout(t)
  }, [activeEntities])

  const W = 420
  const H = 200
  const PAD = { top: 20, right: 20, bottom: 28, left: 32 }
  const chartW = W - PAD.left - PAD.right
  const chartH = H - PAD.top - PAD.bottom

  const mentionMetric = metrics.find(m => m.key === 'mention_rate')
  const rsiMetric     = metrics.find(m => m.key === 'rsi')

  const bubbles = activeEntities.map((code, i) => {
    const mx = mentionMetric?.values[code] || 0
    const ry = rsiMetric?.values[code]     || 0
    const cx = PAD.left + (mx / 100) * chartW
    const cy = PAD.top  + chartH - (ry / 100) * chartH
    return { code, mx, ry, cx, cy, entity: entities.find(e => e.code === code), delay: i * 0.1 }
  })

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg width={W} height={H} style={{ display: 'block' }}>
        {/* Quadrant dividers */}
        <line
          x1={PAD.left + chartW / 2} y1={PAD.top}
          x2={PAD.left + chartW / 2} y2={PAD.top + chartH}
          stroke={T.border} strokeWidth={1} strokeDasharray="4 4"
        />
        <line
          x1={PAD.left} y1={PAD.top + chartH / 2}
          x2={PAD.left + chartW} y2={PAD.top + chartH / 2}
          stroke={T.border} strokeWidth={1} strokeDasharray="4 4"
        />

        {/* Quadrant labels */}
        {[
          { text: 'NICHE LEADERS', x: PAD.left + 4,              y: PAD.top + 12 },
          { text: 'LEADERS',       x: PAD.left + chartW - 4,     y: PAD.top + 12,       anchor: 'end' },
          { text: 'EMERGING',      x: PAD.left + 4,              y: PAD.top + chartH - 6 },
          { text: 'CHALLENGERS',   x: PAD.left + chartW - 4,     y: PAD.top + chartH - 6, anchor: 'end' },
        ].map(q => (
          <text
            key={q.text}
            x={q.x} y={q.y}
            fontSize={9} fontWeight={600}
            textAnchor={q.anchor || 'start'}
            fill={T.slateLight}
            fontFamily="sans-serif"
            style={{ textTransform: 'uppercase', letterSpacing: 1 }}
          >
            {q.text}
          </text>
        ))}

        {/* Axis labels */}
        <text
          x={PAD.left + chartW / 2} y={H - 4}
          fontSize={10} fill={T.slate}
          textAnchor="middle" fontFamily="sans-serif"
        >
          MENTION RATE
        </text>
        <text
          x={12} y={PAD.top + chartH / 2}
          fontSize={10} fill={T.slate}
          textAnchor="middle" fontFamily="sans-serif"
          transform={`rotate(-90, 12, ${PAD.top + chartH / 2})`}
        >
          RSI SCORE
        </text>

        {/* Bubbles */}
        {bubbles.map(b => (
          <g key={b.code}>
            <circle
              cx={b.cx} cy={b.cy} r={18}
              fill={b.entity?.color || T.slate}
              stroke="white" strokeWidth={2}
              style={{
                transform: animated ? 'scale(1)' : 'scale(0)',
                transformOrigin: `${b.cx}px ${b.cy}px`,
                transition: `transform 0.4s cubic-bezier(0.34,1.56,0.64,1) ${b.delay}s`,
              }}
            />
            <text
              x={b.cx} y={b.cy - 22}
              fontSize={10} fill={T.textMid}
              textAnchor="middle" fontFamily="sans-serif"
            >
              {abbrevName(b.entity?.name || b.code)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  )
}

// ─── Stacked bar chart ────────────────────────────────────────────────────────
function PositionIndexChart({ entities, positionData, activeEntities }) {
  const BAR_HEIGHT = 160
  const showCodes  = activeEntities.slice(0, 3)

  const segments = [
    { key: 'top', label: 'TOP',             color: '#1E293B' },
    { key: 'mid', label: 'Position 2 and 3', color: '#64748B' },
    { key: 'low', label: '4+',              color: '#CBD5E1' },
  ]

  return (
    <div>
      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end', marginBottom: 12, justifyContent: 'center' }}>
        {showCodes.map(code => {
          const entity = entities.find(e => e.code === code)
          const data   = positionData[code] || { top: 33, mid: 34, low: 33 }
          return (
            <div key={code} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 80, height: BAR_HEIGHT, display: 'flex', flexDirection: 'column', borderRadius: 6, overflow: 'hidden' }}>
                {segments.map(seg => (
                  <div
                    key={seg.key}
                    style={{
                      background: seg.color,
                      height: `${data[seg.key]}%`,
                      transition: 'height 0.6s ease',
                    }}
                  />
                ))}
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: T.slate, letterSpacing: '0.04em', textAlign: 'center' }}>
                {abbrevName(entity?.name || code)}
              </span>
            </div>
          )
        })}
      </div>

      {/* Legend */}
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
    <div style={{
      background: T.white,
      border: `1px solid ${T.border}`,
      borderRadius: 12,
      padding: 20,
      position: 'relative',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: T.text }}>{title}</span>
        <button style={{ border: 'none', background: 'transparent', color: T.slate, fontSize: 18, cursor: 'pointer', padding: '0 4px' }}>
          ···
        </button>
      </div>
      {children}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function MetricsDashboard({ cycleCode, onNavigate }) {
  const [cycleData,      setCycleData]      = useState(null)
  const [metricsData,    setMetricsData]    = useState(null)
  const [loading,        setLoading]        = useState(true)
  const [activeSlice,    setActiveSlice]    = useState('overall')
  const [activeEntities, setActiveEntities] = useState([])
  const [allCycles,      setAllCycles]      = useState([])

  // ── Data loading ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!cycleCode) {
      const mock = buildMockData(cycleCode)
      setMetricsData(mock)
      setActiveEntities(mock.entities.map(e => e.code))
      setLoading(false)
      return
    }

    let cancelled = false

    const fetchAll = async () => {
      // Cycle metadata
      let cycle = null
      try {
        cycle = await api.getCycle(cycleCode)
      } catch (_) {}

      // Metrics
      let mData = null
      try {
        mData = await api.getMetrics(cycleCode)
      } catch (_) {}

      // All cycles for selector
      let cycles = []
      try {
        cycles = await api.getCycles()
      } catch (_) {}

      if (cancelled) return

      const finalMock = buildMockData(cycleCode)
      setCycleData(cycle || null)
      setMetricsData(mData || finalMock)
      setAllCycles(cycles)
      const entities = (mData || finalMock).entities
      setActiveEntities(entities.map(e => e.code))
      setLoading(false)
    }

    fetchAll()
    return () => { cancelled = true }
  }, [cycleCode])

  // ── Entity toggle ───────────────────────────────────────────────────────────
  function toggleEntity(code) {
    setActiveEntities(prev => {
      if (prev.includes(code)) {
        if (prev.length === 1) return prev // at least one must stay
        return prev.filter(c => c !== code)
      }
      return [...prev, code]
    })
  }

  const { entities = [], metrics = [], positionData = {} } = metricsData || buildMockData(cycleCode)

  const SLICES = [
    { key: 'overall',     label: 'Overall',       soon: false },
    { key: 'by_stage',    label: 'By Stage',      soon: true  },
    { key: 'by_category', label: 'By Category',   soon: true  },
    { key: 'by_platform', label: 'By Platform',   soon: true  },
    { key: 'by_topic',    label: 'By Topic',      soon: true  },
  ]

  const displayCode = cycleCode || '—'

  // ─── RENDER ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", background: T.offWhite }}>
      <style>{`
        @keyframes mdPulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }
        * { box-sizing: border-box; }
        .md-tab-hover:hover { color: ${T.textMid} !important; }
        .md-entity-pill:hover { opacity: 0.85; }
        .md-breadcrumb-link:hover { color: ${T.textMid} !important; }
      `}</style>

      <Sidebar onNavigate={onNavigate} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh', overflow: 'hidden' }}>

        {/* ── Topbar ──────────────────────────────────────────────────────── */}
        <div style={{
          height: 56,
          background: T.white,
          borderBottom: `1px solid ${T.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 28px', flexShrink: 0,
        }}>
          <div style={{ fontSize: 13, color: T.slate, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span
              className="md-breadcrumb-link"
              onClick={() => onNavigate && onNavigate('dashboard')}
              style={{ color: T.slate, cursor: 'pointer', transition: 'color 0.1s' }}
            >
              Cycles
            </span>
            <span style={{ color: T.slateLight, margin: '0 2px' }}>›</span>
            <span
              className="md-breadcrumb-link"
              onClick={() => onNavigate && onNavigate('dashboard')}
              style={{ color: T.textMid, cursor: 'pointer', transition: 'color 0.1s', fontFamily: 'monospace', fontSize: 12 }}
            >
              {displayCode}
            </span>
            <span style={{ color: T.slateLight, margin: '0 2px' }}>›</span>
            <span style={{ color: T.text, fontWeight: 700 }}>Metrics</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            {/* Cycle selector */}
            <div style={{ position: 'relative' }}>
              <select
                value={displayCode}
                onChange={e => onNavigate && onNavigate('metrics', { cycleCode: e.target.value })}
                style={{
                  background: T.navy,
                  color: T.white,
                  border: 'none',
                  borderRadius: 8,
                  padding: '8px 14px',
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: 'pointer',
                  appearance: 'none',
                  paddingRight: 28,
                  outline: 'none',
                }}
              >
                {allCycles.length > 0
                  ? allCycles.map(c => (
                      <option key={c.cycle_code} value={c.cycle_code}>
                        Cycle: {c.cycle_code}
                      </option>
                    ))
                  : <option value={displayCode}>Cycle: {displayCode}</option>
                }
              </select>
              <span style={{
                position: 'absolute', right: 10, top: '50%',
                transform: 'translateY(-50%)',
                color: T.sidebarText, fontSize: 10, pointerEvents: 'none',
              }}>▾</span>
            </div>

            <span style={{ fontSize: 18, cursor: 'pointer' }}>🔔</span>
            <div style={{
              width: 32, height: 32, borderRadius: '50%',
              background: T.indigo, color: T.white,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 13, fontWeight: 700,
            }}>E</div>
          </div>
        </div>

        {/* ── Entity filter row ────────────────────────────────────────────── */}
        <div style={{
          background: T.white,
          borderBottom: `1px solid ${T.border}`,
          padding: '12px 28px',
          display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
          flexShrink: 0,
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
                  padding: '6px 14px',
                  borderRadius: 20,
                  border: isActive ? 'none' : `1px solid ${T.border}`,
                  background: isActive ? T.navy : T.white,
                  color: isActive ? T.white : T.textMid,
                  fontSize: 13, fontWeight: 600,
                  cursor: 'pointer',
                  transition: 'all 0.12s',
                }}
              >
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: isActive ? entity.color : T.slateLight,
                  flexShrink: 0,
                }} />
                {entity.name}
                <span style={{ fontSize: 10 }}>▾</span>
              </button>
            )
          })}
        </div>

        {/* ── Slice tabs ───────────────────────────────────────────────────── */}
        <div style={{
          background: T.white,
          borderBottom: `1px solid ${T.border}`,
          padding: '0 28px',
          display: 'flex', alignItems: 'center',
          flexShrink: 0,
        }}>
          {SLICES.map(slice => {
            const isActive = activeSlice === slice.key
            return (
              <div
                key={slice.key}
                className="md-tab-hover"
                title={slice.soon ? 'Coming soon' : undefined}
                onClick={() => setActiveSlice(slice.key)}
                style={{
                  padding: '14px 4px',
                  marginRight: 28,
                  fontSize: 14,
                  fontWeight: isActive ? 700 : 500,
                  color: isActive ? T.text : T.slate,
                  borderBottom: isActive ? `2px solid ${T.text}` : '2px solid transparent',
                  marginBottom: -1,
                  cursor: 'pointer',
                  opacity: slice.soon ? 0.5 : 1,
                  transition: 'color 0.1s',
                  userSelect: 'none',
                  whiteSpace: 'nowrap',
                }}
              >
                {slice.label}
              </div>
            )
          })}
        </div>

        {/* ── Content area ─────────────────────────────────────────────────── */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px', background: T.offWhite }}>

          {/* Coming-soon placeholder for non-overall slices */}
          {activeSlice !== 'overall' && (
            <div style={{
              background: T.white,
              border: `1px solid ${T.border}`,
              borderRadius: 12,
              padding: '64px 32px',
              textAlign: 'center',
            }}>
              <div style={{ fontSize: 32, marginBottom: 16 }}>📊</div>
              <h3 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 700, color: T.text }}>
                {SLICES.find(s => s.key === activeSlice)?.label} slice coming soon
              </h3>
              <p style={{ margin: '0 auto', fontSize: 14, color: T.slate, maxWidth: 420 }}>
                Run more cycles to unlock dimensional breakdowns.
              </p>
            </div>
          )}

          {activeSlice === 'overall' && (
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
                  <div style={{
                    background: T.white,
                    border: `1px solid ${T.border}`,
                    borderRadius: 12,
                    overflow: 'hidden',
                    marginBottom: 20,
                  }}>
                    <div style={{
                      padding: '16px 20px',
                      borderBottom: `1px solid ${T.border}`,
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    }}>
                      <span style={{ fontSize: 16, fontWeight: 700, color: T.text }}>Summary Scorecard</span>
                      <span style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.slate }}>
                        ALL DATA NORMALIZED TO SCALE [0-100]
                      </span>
                    </div>

                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ background: T.offWhite, height: 36, borderBottom: `1px solid ${T.border}` }}>
                          <th style={{ padding: '0 20px', width: 220, textAlign: 'left', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: T.slate, letterSpacing: '0.05em' }}>
                            METRIC
                          </th>
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
                        {metrics.map((metric, mi) => (
                          <tr
                            key={metric.key}
                            style={{
                              height: 44,
                              borderBottom: mi < metrics.length - 1 ? `1px solid ${T.border}` : 'none',
                            }}
                          >
                            <td style={{ padding: '0 20px', fontSize: 13, fontWeight: 600, color: T.text }}>
                              {metric.label}
                            </td>
                            {activeEntities.map(code => {
                              const v = metric.values[code] ?? 0
                              return (
                                <td key={code} style={{ textAlign: 'center' }}>
                                  <span style={{
                                    fontSize: 14,
                                    fontWeight: 700,
                                    fontFamily: 'monospace',
                                    color: heatColor(v),
                                  }}>
                                    {formatMetric(v)}
                                  </span>
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
                      <DonutChart
                        entities={entities}
                        metrics={metrics}
                        activeEntities={activeEntities}
                      />
                    </ChartCard>

                    <ChartCard title="Mention Rate (%)">
                      <MentionRateChart
                        entities={entities}
                        metrics={metrics}
                        activeEntities={activeEntities}
                      />
                    </ChartCard>
                  </div>

                  {/* ── SECTION 3: Chart row 2 ─────────────────────────────── */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                    <ChartCard title="Recommendation Strength vs Mention Rate">
                      <ScatterChart
                        entities={entities}
                        metrics={metrics}
                        activeEntities={activeEntities}
                      />
                    </ChartCard>

                    <ChartCard title="Position Index by Quintile">
                      <PositionIndexChart
                        entities={entities}
                        positionData={positionData}
                        activeEntities={activeEntities}
                      />
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
