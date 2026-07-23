/**
 * Shared visual primitives for the SoA Lite widget — colors, layout
 * shells, and small reusable pieces (BarRow, LogoHeader, ErrorBanner).
 * Extracted from LiteWidget.jsx unchanged so LiteForm/LiteProgress/
 * LiteTeaser/LiteFullReport can all import the same look without a
 * circular dependency on the root widget file.
 */
import { useEffect, useState } from 'react'

export const T = {
  navy:       '#0D1829',
  white:      '#FFFFFF',
  offWhite:   '#F8FAFC',
  slate:      '#64748B',
  slateLight: '#94A3B8',
  border:     '#E2E8F0',
  text:       '#0F172A',
  textMid:    '#334155',
  indigo:     '#4F46E5',
  green:      '#16A34A',
  red:        '#DC2626',
  redLight:   '#FEE2E2',
  amber:      '#D97706',
  amberLight: '#FEF3C7',
}

export const BRAND_COLORS = ['#0F172A', '#3B82F6', '#F59E0B']
export const STAGE_ORDER = ['Awareness', 'Research', 'Comparison', 'Ready to Buy']

export function formatRsi(v) {
  if (v === null || v === undefined) return '—'
  return v.toFixed(2)
}

export function formatPct(v) {
  if (v === null || v === undefined) return '—'
  return `${v.toFixed(1)}%`
}

export function formatScore(v) {
  if (v === null || v === undefined) return '—'
  return `${Math.round(v)}`
}

// ─── Shared layout ─────────────────────────────────────────────────────────

export const outerStyle = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '24px 16px',
  fontFamily: "'DM Sans', sans-serif",
  display: 'flex',
  justifyContent: 'center',
}

export const cardStyle = {
  width: '100%',
  maxWidth: 480,
  boxSizing: 'border-box',
  background: T.white,
  border: `1px solid ${T.border}`,
  borderRadius: 12,
  padding: 28,
}

// A wider card for the full report — the why-section, fix list, and
// exposure calculator all read cramped at 480px once the report grew
// this much content. Teaser and progress views keep the narrow card.
export const wideCardStyle = {
  ...cardStyle,
  maxWidth: 640,
}

export function LogoHeader() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
        <rect x="2" y="2" width="8" height="20" rx="1.5" fill={T.indigo} />
        <rect x="14" y="6" width="8" height="12" rx="1.5" fill={T.indigo} opacity="0.4" />
      </svg>
      <span style={{ fontSize: 16, fontWeight: 700, color: T.text, letterSpacing: '0.04em' }}>
        SoA Lite
      </span>
    </div>
  )
}

export function ErrorBanner({ message }) {
  if (!message) return null
  return (
    <div style={{
      background: T.redLight,
      border: '1px solid #FECACA',
      borderRadius: 6,
      padding: '10px 14px',
      fontSize: 13,
      color: '#991B1B',
      marginBottom: 16,
    }}>
      {message}
    </div>
  )
}

/** Neutral, non-alarming badge — used for honest scan-blocked/failed
 * states that are findings, not errors (rule: never an error state). */
export function InfoBadge({ message }) {
  if (!message) return null
  return (
    <div style={{
      background: T.amberLight,
      border: '1px solid #FDE68A',
      borderRadius: 6,
      padding: '10px 14px',
      fontSize: 12,
      lineHeight: 1.5,
      color: '#92400E',
    }}>
      {message}
    </div>
  )
}

// ─── Horizontal bar (reuses MetricsDashboard.jsx's bar-chart pattern) ──────

export function BarRow({ label, value, color, delay = 0, animated }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: T.textMid }}>{label}</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: T.textMid, fontFamily: 'monospace' }}>
          {formatPct(value)}
        </span>
      </div>
      <div style={{ height: 8, background: T.border, borderRadius: 4, overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: animated ? `${value || 0}%` : '0%',
          background: color,
          borderRadius: 4,
          transition: `width 0.8s ease ${delay}s`,
        }} />
      </div>
    </div>
  )
}

// ─── Score dial (composite/visibility/accessibility) ───────────────────────

/** Radial gauge, 0-100. `dimmed` + `badge` cover the "accessibility not
 * ready yet" case — the dial itself never disappears, it just visibly
 * recedes with an honest status label instead of showing a fake number. */
export function ScoreDial({ label, value, color = T.indigo, dimmed = false, badge = null, size = 88 }) {
  const radius = (size - 10) / 2
  const circumference = 2 * Math.PI * radius
  const pct = value === null || value === undefined ? 0 : Math.max(0, Math.min(100, value))
  const offset = circumference * (1 - pct / 100)

  return (
    <div style={{ textAlign: 'center', opacity: dimmed ? 0.45 : 1, transition: 'opacity 0.4s ease' }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={T.border} strokeWidth={8} />
        <circle
          cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={color} strokeWidth={8}
          strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 0.8s ease' }}
        />
        <text
          x="50%" y="50%" textAnchor="middle" dominantBaseline="central"
          fontSize={size * 0.22} fontWeight="700" fill={T.text}
        >
          {value === null || value === undefined ? '—' : Math.round(value)}
        </text>
      </svg>
      <div style={{ fontSize: 12, fontWeight: 600, color: T.textMid, marginTop: 4 }}>{label}</div>
      {badge && <div style={{ fontSize: 10, color: T.amber, fontWeight: 700, marginTop: 2 }}>{badge}</div>}
    </div>
  )
}

export function useAnimateOnMount() {
  const [animated, setAnimated] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 80)
    return () => clearTimeout(t)
  }, [])
  return animated
}
