/**
 * Shared visual primitives for the SoA Lite widget, matching the Parleo
 * Scan report design language (Stage 5 — see design-refs/ screenshots).
 * Every component here expects to render inside the .lite-root wrapper
 * (see theme.css) so its CSS custom properties resolve.
 */
import { useEffect, useState } from 'react'
import { SCORE_BANDS } from './liteDerive.js'
import { reportUrl } from './publicUrls.js'

export const STAGE_ORDER = ['Awareness', 'Research', 'Comparison', 'Ready to Buy']

// Primary entity vs up to 5 competitors (Stage 13: auto-generated
// competitors can bring the comparison set to 6 total). Index 0 is
// always --accent, kept visually dominant per the reference design's
// "you vs rivals" framing; indices 1-5 are the muted, colorblind-safe
// rival tones (theme.css --rival-1..5) — a 1-2 rival report renders
// pixel-identical to before this stage since --rival-1/2 reuse the
// original two colors.
export const ENTITY_COLORS = [
  'var(--accent)',
  'var(--rival-1)', 'var(--rival-2)', 'var(--rival-3)', 'var(--rival-4)', 'var(--rival-5)',
]

// Stage 21 (V1): a monochrome ramp for the visualization-first report's
// mention-rate/share-of-mentions charts — you in --accent (with an
// inline "YOU" tag) against a slate-to-light-grey ramp for rivals,
// de-emphasizing individual rival identity by hue (doesn't scale as
// cleanly as a rank ramp once there are 5-6 of them) in favor of a
// clean "you vs. the field" read. --foundation is the same hex the
// design mock calls --slate; cycles by index like ENTITY_COLORS.
export const RIVAL_SLATE_RAMP = ['var(--foundation)', '#8890A0', '#B9BEC9']

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
      <span className="lite-label" style={{ fontSize: 12 }}>Parleo Audit</span>
    </div>
  )
}

// ─── Report header bar (page frame, item 1) ────────────────────────────

const SCAN_STATUS_COPY = {
  complete: 'Audit complete',
  blocked: 'Store blocked',
  failed: 'Audit failed',
  skipped: 'No store audited',
  running: 'Auditing…',
  pending: 'Auditing…',
}

function scanStatusTone(scanStatus) {
  if (scanStatus === 'complete') return 'good'
  if (scanStatus === 'blocked' || scanStatus === 'failed') return 'bad'
  return 'warn'
}

export function ReportHeaderBar({ brandOrDomain, scannedDateLabel, scanStatus, token }) {
  const [copied, setCopied] = useState(false)
  const statusText = SCAN_STATUS_COPY[scanStatus] || 'Auditing…'
  const tone = scanStatusTone(scanStatus)

  async function handleCopyLink() {
    // Stage 9 (U3), extended by the audit.parleo.io migration's U1-U3:
    // the canonical /r/{token} URL on PUBLIC_AUDIT_BASE_URL, built
    // explicitly rather than trusting window.location.href — this bar
    // can render while the page is still at the legacy /lite path
    // (sessionStorage-resumed) on the marketing host, where location
    // would point at the wrong host entirely, not just an unshareable
    // path. Falls back to location.href only if no token was threaded
    // down (shouldn't happen on the full report, which always has one
    // by the time it renders).
    const url = token ? reportUrl(token) : window.location.href
    try {
      await navigator.clipboard.writeText(url)
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

export function LightCard({ children, style, id }) {
  return (
    <div className="lite-card" style={style} id={id}>
      <span className="lite-corner lite-corner--tl" aria-hidden="true" />
      <span className="lite-corner lite-corner--tr" aria-hidden="true" />
      <span className="lite-corner lite-corner--bl" aria-hidden="true" />
      <span className="lite-corner lite-corner--br" aria-hidden="true" />
      {children}
    </div>
  )
}

export function DarkCard({ children, style, id, className }) {
  return <div className={`lite-card-dark${className ? ` ${className}` : ''}`} style={style} id={id}>{children}</div>
}

// ─── Full Diagnostic gate (Part 1) ─────────────────────────────────────
// The ONE standardized paid-tier overlay pattern in the report — Part 1
// (M1) consolidates what used to be bespoke per-section overlays (the
// funnel teaser, the fixes list's locked tail) into this single module,
// so the report makes ONE offer with ONE label everywhere it appears
// (M2). `children` must be decorative-only data (fixed DECORATIVE_*
// constants a caller defines itself) — never real gated data blurred,
// which would be a leak dressed up as a gate. No email language lives
// here, ever: this module's vocabulary is exclusively paid-tier.
export const FULL_DIAGNOSTIC_CTA_LABEL = 'Contact us for a free custom Full Diagnostic'

// Report redesign (Part 6, G1): fully self-contained styling via an
// inline style object, not a className alone — an ancestor rule (a card
// background, an inverse-text context) can never restyle this pill,
// since nothing here is left for the cascade to override. The same
// component mounts in three places (funnel, fixes, closing module) and
// must render byte-identical computed style in every one of them (see
// the computed-style-equality test in LiteFullReport.test.jsx).
const FULL_ANALYSIS_PILL_STYLE = {
  display: 'inline-block',
  fontFamily: 'var(--mono)',
  fontSize: 10,
  letterSpacing: '0.22em',
  fontWeight: 600,
  color: '#E8A33D',
  border: '1.5px solid #E8A33D',
  borderRadius: 999,
  padding: '6px 16px 5px',
  background: 'none',
}

export function FullAnalysisPill() {
  return <span style={FULL_ANALYSIS_PILL_STYLE}>FULL ANALYSIS</span>
}

// Report redesign (Part 6, G1): ONE gate component, two layouts.
// 'inline' — message (with the pill) left, CTA right, in a slim dark
// bar; used for in-flow teasers (funnel, fixes) that sit immediately
// after their own (separately blurred) decorative preview — the gate
// itself never blurs anything anymore; a caller wanting a decorative
// preview renders it itself, outside this component, same G2 discipline
// as before. 'block' — pill, heading, a free content slot, then the
// CTA; the closing, full-width module before the footer.
export function FullDiagnosticGate({
  variant = 'inline', message, subMessage, heading, cta = FULL_DIAGNOSTIC_CTA_LABEL, ctaUrl, children,
}) {
  if (variant === 'block') {
    return (
      <DarkCard className="lite-fdg-block">
        <FullAnalysisPill />
        {heading && <h3 className="lite-fdg-heading">{heading}</h3>}
        {children}
        {ctaUrl && (
          <a href={ctaUrl} target="_blank" rel="noreferrer" className="lite-pill lite-pill--solid">
            {cta}
          </a>
        )}
      </DarkCard>
    )
  }
  return (
    <div className="lite-fdg-inline">
      <div className="lite-fdg-inline-m">
        <FullAnalysisPill />
        <br />
        {message}
        {subMessage && <span className="lite-fdg-cnt">{subMessage}</span>}
      </div>
      {ctaUrl && (
        <a href={ctaUrl} target="_blank" rel="noreferrer" className="lite-pill lite-pill--solid">
          {cta}
        </a>
      )}
    </div>
  )
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
