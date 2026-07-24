/**
 * METHODOLOGY — section [2]. Weights bar mirrors the scan engine's real
 * 8-dimension rubric (see apps/pipeline/scan/scorer.py) — Foundation 35 /
 * Value 65, same dimension names and point values used in the real
 * report's why-section (LiteFullReport.jsx).
 */
import { SectionHeader } from '../liteTheme.jsx'
import { WeightsBar } from './landingTheme.jsx'

const FOUNDATION_SEGMENTS = [
  { label: 'Agent Access', weight: 10, color: 'var(--foundation)' },
  { label: 'Catalog & Context', weight: 15, color: 'var(--foundation)' },
  { label: 'Transaction Rails', weight: 10, color: 'var(--foundation)' },
]
const VALUE_SEGMENTS = [
  { label: 'Offer Legibility', weight: 15, color: 'var(--accent)' },
  { label: 'Loyalty Program Surface', weight: 14, color: 'var(--accent)' },
  { label: 'Member Value Encoding', weight: 14, color: 'var(--accent-ink)' },
  { label: 'Value Rails', weight: 10, color: 'var(--accent-ink)' },
  { label: 'Offer Integrity', weight: 12, color: 'var(--accent-ink)' },
]

export function Methodology() {
  return (
    <section className="lite-landing-section" id="methodology">
      <SectionHeader label="METHODOLOGY" />
      <h2 className="lite-display-headline" style={{ fontSize: 'clamp(28px, 4.5vw, 48px)' }}>
        Agents are already <span className="lite-serif-italic">pricing</span> your store.
      </h2>

      <div className="lite-cols-2" style={{ marginTop: 32, marginBottom: 40 }}>
        <p className="lite-body lite-muted" style={{ fontSize: 15 }}>
          Shopping agents already read your store, compare it against
          rivals, and decide what to tell a customer to buy — with or
          without your input. Most of that reasoning happens on price and
          value signals no storefront was built to expose.
        </p>
        <p className="lite-body lite-muted" style={{ fontSize: 15 }}>
          The scan reads your store the same way, then scores what an
          agent could actually use: not whether a page renders, but
          whether the price, the membership discount, and the offer terms
          on it are legible enough for an agent to quote correctly.
        </p>
      </div>

      <div className="lite-card">
        <div className="lite-cols-2" style={{ marginBottom: 16 }}>
          <div className="lite-label">Foundation 35 pts</div>
          <div className="lite-label" style={{ color: 'var(--accent-ink)' }}>Value 65 pts</div>
        </div>
        <WeightsBar segments={[...FOUNDATION_SEGMENTS, ...VALUE_SEGMENTS]} />
        <div className="lite-body lite-muted" style={{ fontSize: 13, marginTop: 20 }}>
          65 of the accessibility points sit on the value side, because that
          is what every other readiness tool skips.
        </div>
      </div>

      <div className="lite-strip" style={{ marginTop: 20 }}>
        <span className="lite-chip lite-chip--bad">Score cap</span>
        <span className="lite-body" style={{ fontSize: 13.5 }}>
          Dishonest pricing signals cap any score at 59. Google already
          discards fake was-prices. Agents inherit that reflex.
        </span>
      </div>

      <div className="lite-mono lite-muted" style={{ fontSize: 11.5, marginTop: 24 }}>
        12 queries · 1 platform · 1 run each · sample, not a category study.
      </div>
    </section>
  )
}
