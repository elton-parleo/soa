/**
 * Shared visual primitives for the SoA Lite widget, matching the Parleo
 * Scan report design language (Stage 5 — see design-refs/ screenshots).
 * Every component here expects to render inside the .lite-root wrapper
 * (see theme.css) so its CSS custom properties resolve.
 */
import { useEffect, useState } from 'react'
import { SCORE_BANDS } from './liteDerive.js'

export const STAGE_ORDER = ['Awareness', 'Research', 'Comparison', 'Ready to Buy']

// Primary entity vs up to two competitors — semantic accent/neutral duo
// rather than a rotating categorical palette, matching the reference
// design's "you vs rival" framing.
export const ENTITY_COLORS = ['var(--accent)', 'var(--foundation)', '#8890A0']

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

export function useAnimateOnMount() {
  const [animated, setAnimated] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 80)
    return () => clearTimeout(t)
  }, [])
  return animated
}

// ─── Brand mark (pre-report views only — the report views use
// ReportHeaderBar instead, matching the reference design's economy of
// showing the Parleo mark once, not on every card) ─────────────────────

export function LogoHeader() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="2" y="2" width="8" height="20" rx="1.5" style={{ fill: 'var(--accent)' }} />
        <rect x="14" y="6" width="8" height="12" rx="1.5" style={{ fill: 'var(--accent)' }} opacity="0.4" />
      </svg>
      <span className="lite-label" style={{ fontSize: 12 }}>Parleo Scan</span>
    </div>
  )
}

// ─── Report header bar (page frame, item 1) ────────────────────────────

const SCAN_STATUS_COPY = {
  complete: 'Scan complete',
  blocked: 'Store blocked',
  failed: 'Scan failed',
  skipped: 'No store scanned',
  running: 'Scanning…',
  pending: 'Scanning…',
}

function scanStatusTone(scanStatus) {
  if (scanStatus === 'complete') return 'good'
  if (scanStatus === 'blocked' || scanStatus === 'failed') return 'bad'
  return 'warn'
}

export function ReportHeaderBar({ brandOrDomain, scannedDateLabel, scanStatus }) {
  const [copied, setCopied] = useState(false)
  const statusText = SCAN_STATUS_COPY[scanStatus] || 'Scanning…'
  const tone = scanStatusTone(scanStatus)

  async function handleCopyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch (_) {
      // Clipboard access can be denied by the embedding context — the
      // pill just silently no-ops rather than showing an error state
      // for a non-essential convenience action.
    }
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
      <div>
        <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>{brandOrDomain}</span>
        {scannedDateLabel && (
          <span className="lite-muted" style={{ fontSize: 13, marginLeft: 10 }}>Scanned {scannedDateLabel}</span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="lite-pill" style={{ cursor: 'default' }}>
          <span className={`lite-badge-dot${tone !== 'good' ? ` lite-badge-dot--${tone}` : ''}`} aria-hidden="true" />
          {statusText}
        </span>
        <button type="button" className="lite-pill" onClick={handleCopyLink}>
          {copied ? 'Copied' : 'Copy link'}
        </button>
      </div>
    </div>
  )
}

// ─── Section header pattern ─────────────────────────────────────────────

export function SectionHeader({ label, headline, annotation, inv }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div className="lite-section-header">
        <div className="lite-section-header-label">
          <span
            className="lite-section-header-rule"
            aria-hidden="true"
            style={inv ? { background: 'var(--text-inv-2)' } : undefined}
          />
          <span className={inv ? 'lite-label lite-label--inv' : 'lite-label'}>{label}</span>
        </div>
        {annotation && (
          <span className={inv ? 'lite-section-annotation lite-section-annotation--inv' : 'lite-section-annotation'}>
            {annotation}
          </span>
        )}
      </div>
      {headline && <h2 className={inv ? 'lite-headline lite-headline--inv' : 'lite-headline'}>{headline}</h2>}
    </div>
  )
}

// ─── Cards ────────────────────────────────────────────────────────────

export function LightCard({ children, style }) {
  return (
    <div className="lite-card" style={style}>
      <span className="lite-corner lite-corner--tl" aria-hidden="true" />
      <span className="lite-corner lite-corner--tr" aria-hidden="true" />
      <span className="lite-corner lite-corner--bl" aria-hidden="true" />
      <span className="lite-corner lite-corner--br" aria-hidden="true" />
      {children}
    </div>
  )
}

export function DarkCard({ children, style }) {
  return <div className="lite-card-dark" style={style}>{children}</div>
}

// ─── Pills & chips ────────────────────────────────────────────────────

export function Pill({ solid, inv, as: As = 'button', className = '', children, ...rest }) {
  const classes = ['lite-pill']
  if (solid) classes.push('lite-pill--solid')
  if (inv && !solid) classes.push('lite-pill--inv')
  if (className) classes.push(className)
  const asProps = As === 'button' && !rest.type ? { type: 'button' } : {}
  return <As className={classes.join(' ')} {...asProps} {...rest}>{children}</As>
}

export function Chip({ tone = 'neutral', children }) {
  return <span className={`lite-chip lite-chip--${tone}`}>{children}</span>
}

// ─── Banners ──────────────────────────────────────────────────────────

export function ErrorBanner({ message }) {
  if (!message) return null
  return (
    <div style={{
      background: 'var(--bad-tint)',
      border: '1px solid var(--bad)',
      borderRadius: 8,
      padding: '10px 14px',
      fontSize: 13,
      color: 'var(--bad-ink)',
      marginBottom: 16,
    }}>
      {message}
    </div>
  )
}

/** Neutral, non-alarming badge — used for honest scan-blocked/failed
 * states that are findings, not errors. Text carries the meaning, not
 * just the (warn) tint, so it reads fine without color. */
export function InfoBadge({ message }) {
  if (!message) return null
  return (
    <div style={{
      background: 'var(--warn-tint)',
      border: '1px solid var(--warn)',
      borderRadius: 8,
      padding: '10px 14px',
      fontSize: 13,
      lineHeight: 1.5,
      color: 'var(--warn-ink)',
    }}>
      {message}
    </div>
  )
}

// ─── Band pill (hero) ───────────────────────────────────────────────────

// These render on --ink (the dark hero card via .lite-pill--inv), not on
// their matching -tint — --warn/--good already clear AA there (5.98:1 /
// 5.20:1); --bad does not (3.65:1), hence --bad-on-dark.
const BAND_TONE_COLOR = {
  bad: 'var(--bad-on-dark)',
  warn: 'var(--warn)',
  neutral: 'var(--text-inv-2)',
  good: 'var(--good)',
}

export function BandPill({ band }) {
  const color = BAND_TONE_COLOR[band.tone] || 'var(--text-inv-2)'
  return (
    <span className="lite-pill lite-pill--inv" style={{ color, borderColor: color, cursor: 'default' }}>
      {band.name} · {band.range}
    </span>
  )
}

// ─── Score band scale (hero) ──────────────────────────────────────────

export function BandScale({ score }) {
  const bounds = [0, ...SCORE_BANDS.map((b) => Math.min(b.max, 100))]
  const clamped = score === null || score === undefined ? 0 : Math.max(0, Math.min(100, score))
  return (
    <div style={{ marginTop: 28 }}>
      <div style={{ position: 'relative', marginBottom: 30 }}>
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            left: `${clamped}%`,
            transform: 'translateX(-50%)',
            top: -32,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
          }}
        >
          <span className="lite-mono" style={{
            background: 'var(--text-inv)', color: 'var(--ink)', fontSize: 12, fontWeight: 700,
            padding: '3px 9px', borderRadius: 6, marginBottom: 3,
          }}>
            {score === null || score === undefined ? '—' : Math.round(score)}
          </span>
          <span style={{ width: 1, height: 8, background: 'var(--text-inv)' }} />
        </div>
        <div style={{ display: 'flex', gap: 3, height: 10 }}>
          {SCORE_BANDS.map((band, i) => (
            <div key={band.name} style={{
              flexBasis: `${bounds[i + 1] - bounds[i]}%`,
              background: 'rgba(255,255,255,0.1)',
              borderRadius: 3,
            }} />
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 3 }}>
        {SCORE_BANDS.map((band, i) => (
          <div
            key={band.name}
            className="lite-label lite-label--inv"
            style={{ flexBasis: `${bounds[i + 1] - bounds[i]}%`, fontSize: 10 }}
          >
            {band.shortLabel.toUpperCase()}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Family bar ("Score by family" — visibility/accessibility) ────────

export function FamilyBar({ label, description, value, max = 100, color, inv = true, badge }) {
  const pct = max ? Math.max(0, Math.min(100, ((value || 0) / max) * 100)) : 0
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ fontSize: 13, color: inv ? 'var(--text-inv)' : 'var(--text)', marginBottom: 6 }}>
        {label}
        {description && (
          <span className={inv ? 'lite-muted--inv' : 'lite-muted'}> · {description}</span>
        )}
      </div>
      {badge ? (
        <span className={`lite-pill${inv ? ' lite-pill--inv' : ''}`} style={{ fontSize: 12, padding: '6px 14px', cursor: 'default' }}>
          {badge}
        </span>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className={`lite-bar-track${inv ? ' lite-bar-track--inv' : ''}`} style={{ flex: 1 }}>
            <div className="lite-bar-fill" style={{ width: `${pct}%`, background: color }} />
          </div>
          <span
            className="lite-mono"
            style={{
              fontSize: 13, fontWeight: 700, minWidth: 52, textAlign: 'right',
              color: inv ? 'var(--text-inv)' : 'var(--text)',
            }}
          >
            {value === null || value === undefined ? '—' : Math.round(value)}/{max}
          </span>
        </div>
      )}
    </div>
  )
}
