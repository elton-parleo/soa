/**
 * Shared visual primitives for the scan.parleo.io landing page (Stage 6),
 * built on top of ../liteTheme.jsx's report primitives. Everything here
 * is presentational — no data fetching, no submit-flow logic.
 */
import { BandScale, FamilyBar } from '../liteTheme.jsx'

// ─── Trust chip (outlined pill, small icon + text) ─────────────────────

export function TrustChip({ icon, children }) {
  return (
    <span className="lite-trust-chip">
      <span aria-hidden="true">{icon}</span>
      {children}
    </span>
  )
}

// ─── Privacy note (bordered card, lock glyph) ──────────────────────────

export function PrivacyNote({ children }) {
  return (
    <div className="lite-privacy-note">
      <span aria-hidden="true" style={{ fontSize: 15, lineHeight: 1 }}>🔒</span>
      <span>{children}</span>
    </div>
  )
}

// ─── Sample-teaser card ─────────────────────────────────────────────────
// No real sample-report token exists in the repo yet (checked before
// building this) — href is intentionally "#" per the Stage 6 truth rules
// rather than fabricating a fake report page.

export function SampleTeaserCard({ href = '#', score, label, linkText, meta }) {
  return (
    <a href={href} className="lite-teaser-card" style={{ textDecoration: 'none', color: 'inherit' }}>
      <span className="lite-teaser-score-tile" aria-hidden="true">
        <span className="lite-numeral" style={{ fontSize: 20, color: 'var(--text-inv)' }}>{score}</span>
        <span style={{ fontSize: 9, color: 'var(--text-inv-2)' }}>/100</span>
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span className="lite-label" style={{ display: 'block', marginBottom: 4 }}>
          <span className="lite-badge-dot" aria-hidden="true" style={{ marginRight: 5 }} />
          {label}
        </span>
        <span style={{ display: 'block', fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>{linkText}</span>
        <span className="lite-muted" style={{ display: 'block', fontSize: 12, marginTop: 2 }}>{meta}</span>
      </span>
      <span className="lite-teaser-arrow-btn" aria-hidden="true">→</span>
    </a>
  )
}

// ─── Report preview mock (hero right) ──────────────────────────────────
// Real DOM, not an image. Illustrative placeholder content (no real scan
// has produced these numbers — see the Stage 6 diagnosis re: T5).

export function ReportPreviewMock({ domain = 'yourstore.com', score = 57, foundation = { value: 24, max: 35 }, value = { value: 33, max: 65 } }) {
  const findings = [
    { tone: 'good', text: 'Products readable: price, stock, and brand parse cleanly.' },
    { tone: 'good', text: 'All four agent platforms can reach the site.' },
    { tone: 'bad', text: 'Member value is not machine-readable: dividend, card, coupons.' },
    { tone: 'bad', text: 'Offers carry no expiry or sale encoding agents trust.' },
  ]

  return (
    <div className="lite-card" style={{ padding: 0, overflow: 'hidden' }} aria-hidden="true">
      <div className="lite-browser-chrome">
        <span className="lite-chrome-dots">
          <span className="lite-chrome-dot" /><span className="lite-chrome-dot" /><span className="lite-chrome-dot" />
        </span>
        <span className="lite-chrome-url-pill">parleo.io/report/{domain}</span>
        <span className="lite-sample-tag">Sample report</span>
      </div>
      <div style={{ background: 'var(--ink)', padding: 24, color: 'var(--text-inv)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
          <span className="lite-label lite-label--inv">Agent commerce score</span>
          <span className="lite-mono lite-muted--inv" style={{ fontSize: 12 }}>{domain}</span>
        </div>
        <div className="lite-numeral lite-numeral--tile" style={{ color: 'var(--text-inv)' }}>
          {score}<span style={{ fontSize: '0.4em', color: 'var(--text-inv-2)' }}>/100</span>
        </div>
        <BandScale score={score} />
      </div>
      <div style={{ padding: 24 }}>
        <FamilyBar label="Foundation" description="Can agents find and transact with your store?" value={foundation.value} max={foundation.max} color="var(--foundation)" inv={false} />
        <FamilyBar label="Value" description="Can agents see what customers actually pay?" value={value.value} max={value.max} color="var(--accent)" inv={false} />
        <div className="lite-body lite-muted" style={{ fontSize: 12.5, marginBottom: 14 }}>
          9 incentives found. Agents can price 0 of them.
        </div>
        <div className="lite-preview-findings-grid">
          {findings.map((f, i) => (
            <div key={i} className="lite-preview-finding">
              <span className={`lite-preview-finding-tag lite-preview-finding-tag--${f.tone}`}>
                <span className={`lite-preview-finding-swatch lite-preview-finding-swatch--${f.tone}`} />
                {f.tone === 'good' ? 'Good' : 'Poor'}
              </span>
              {f.text}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ─── Brand / platform chip (ChatGPT, Gemini, Perplexity, Copilot, and
// the field-evidence monogram badges) — no third-party logo assets exist
// in the repo, so this renders a mono-letter glyph rather than hotlinking
// or fabricating a brand mark. ─────────────────────────────────────────

export function BrandChip({ label, glyph }) {
  return (
    <span className="lite-brand-chip">
      <span className="lite-brand-chip-glyph">{glyph || label.charAt(0)}</span>
      {label}
    </span>
  )
}

// ─── Weights bar (methodology) ─────────────────────────────────────────

export function WeightsBar({ segments }) {
  const total = segments.reduce((sum, s) => sum + s.weight, 0)
  return (
    <div>
      <div className="lite-weights-bar" role="img" aria-label={`Score weighting: ${segments.map((s) => `${s.label} ${s.weight} points`).join(', ')}`}>
        {segments.map((s) => (
          <div
            key={s.label}
            className="lite-weights-segment"
            style={{ flexBasis: `${(s.weight / total) * 100}%`, background: s.color }}
          >
            {s.weight}
          </div>
        ))}
      </div>
      <div className="lite-weights-legend" style={{ marginTop: 16 }}>
        {segments.map((s) => (
          <div key={s.label} className="lite-weights-legend-item">
            <span className="lite-weights-swatch" style={{ background: s.color }} />
            {s.label} {s.weight}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Path column (THE PATH, 4-up) ──────────────────────────────────────

export function PathColumn({ dotColor, kicker, title, description }) {
  return (
    <div>
      <div className="lite-label" style={{ marginBottom: 10, color: dotColor }}>
        <span className="lite-kicker-dot" style={{ background: dotColor }} aria-hidden="true" />
        {kicker}
      </div>
      <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)', marginBottom: 6 }}>{title}</div>
      <div className="lite-body lite-muted" style={{ fontSize: 13 }}>{description}</div>
    </div>
  )
}
