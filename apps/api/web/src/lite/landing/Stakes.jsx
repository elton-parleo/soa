/**
 * THE STAKES — section [5]. Reuses computeExposure from ../liteDerive.js
 * verbatim (same function the real report's exposure calculator calls —
 * see LiteFullReport.jsx's ExposureCalculator) so landing and report can
 * never disagree; no new math lives here.
 *
 * The two interactive sliders (revenue, member share) scope down to a
 * "revenue pool exposed to invisible value" using the static
 * incentive-influenced-revenue rate, then computeExposure is called
 * twice — once at each end of the static agent-influenced-discovery
 * range — to produce a live low/high range instead of a single point
 * estimate (the report only ever needs a point estimate, since it has a
 * real per-brand visibility score; the landing page doesn't).
 */
import { useState } from 'react'
import { SectionHeader } from '../liteTheme.jsx'
import { computeExposure } from '../liteDerive.js'

const DEFAULT_REVENUE = 200_000_000
const DEFAULT_MEMBER_SHARE_PCT = 40
const INCENTIVE_INFLUENCED_PCT = 60
const AGENT_DISCOVERY_RANGE = [8, 13]

function formatMillions(n) {
  return `$${(n / 1_000_000).toFixed(1)}M`
}

export function Stakes() {
  const [revenue, setRevenue] = useState(DEFAULT_REVENUE)
  const [memberSharePct, setMemberSharePct] = useState(DEFAULT_MEMBER_SHARE_PCT)

  const revenuePool = revenue * (memberSharePct / 100) * (INCENTIVE_INFLUENCED_PCT / 100)
  const [lowPct, highPct] = AGENT_DISCOVERY_RANGE
  const exposureLow = computeExposure({ revenue: revenuePool, aiSharePct: lowPct, visibility: 0 })
  const exposureHigh = computeExposure({ revenue: revenuePool, aiSharePct: highPct, visibility: 0 })

  return (
    <section className="lite-landing-section" style={{ background: 'var(--ink)', maxWidth: 'none', padding: 0 }}>
      <div style={{ maxWidth: 1120, margin: '0 auto', padding: '64px 20px' }}>
        <SectionHeader inv label="THE STAKES" />
        <h2 className="lite-display-headline lite-display-headline--inv" style={{ fontSize: 'clamp(28px, 4.5vw, 48px)' }}>
          What's at stake for a store <span className="lite-serif-italic">your size</span>.
        </h2>

        <div className="lite-cols-2" style={{ marginTop: 40, gap: 48, alignItems: 'start' }}>
          <div>
            <label className="lite-label lite-label--inv" style={{ display: 'block', marginBottom: 8 }}>
              Annual online revenue: {formatMillions(revenue)}
            </label>
            <input
              type="range" min={1_000_000} max={500_000_000} step={1_000_000}
              value={revenue} onChange={(e) => setRevenue(Number(e.target.value))}
              className="lite-slider" style={{ marginBottom: 26 }}
              aria-label="Annual online revenue"
            />

            <label className="lite-label lite-label--inv" style={{ display: 'block', marginBottom: 8 }}>
              Member share of revenue: {memberSharePct}%
            </label>
            <input
              type="range" min={0} max={100} step={1}
              value={memberSharePct} onChange={(e) => setMemberSharePct(Number(e.target.value))}
              className="lite-slider" style={{ marginBottom: 26 }}
              aria-label="Member share of revenue"
            />

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--text-inv-2)', padding: '10px 0', borderTop: '1px solid var(--line-dark)' }}>
              <span>Incentive-influenced revenue</span>
              <span className="lite-mono">{INCENTIVE_INFLUENCED_PCT}%</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--text-inv-2)', padding: '10px 0', borderTop: '1px solid var(--line-dark)' }}>
              <span>Agent-influenced discovery</span>
              <span className="lite-mono">{lowPct} to {highPct}%</span>
            </div>
          </div>

          <div>
            <span className="lite-chip lite-chip--warn" style={{ marginBottom: 14, display: 'inline-block' }}>● Modeled</span>
            <div className="lite-body--inv" style={{ fontSize: 14, marginBottom: 6 }}>
              Modeled annual revenue exposed to invisible value
            </div>
            <div className="lite-mono lite-muted--inv" style={{ fontSize: 12, marginBottom: 16 }}>
              About 60% of retail revenue moves on incentives agents can't count
            </div>
            <div className="lite-numeral lite-numeral--tile lite-numeral--inv" style={{ marginBottom: 16 }}>
              {formatMillions(exposureLow)}<span style={{ margin: '0 10px', color: 'var(--text-inv-2)' }}>–</span>{formatMillions(exposureHigh)}
            </div>
            <p className="lite-body--inv" style={{ fontSize: 13.5 }}>
              A modeled range with a deliberate haircut, not a measurement.
              The measured number comes from a Parleo diagnostic.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
