/**
 * THE STAKES — V4 design, section [3] (moved earlier per the mock,
 * right after the proof band). L2: drops the mock's own member-share
 * slider, fixed 60% incentive share, 8-13% agent-discovery band, and
 * low-high range — none of that model is implemented and the 60%
 * figure has no citation to stand behind. Kept: the visual treatment
 * (DarkPanel, two-column layout, big number), driven by the real,
 * shared computeExposure module (same one the report's exposure
 * section imports — see liteDerive.js) instead.
 *
 * Two real inputs: revenue and AI-assisted share. This widget has no
 * specific brand scored yet, so `trueValueScore` (computeExposure's
 * third input) is 0 — full invisibility, framing the number as "what is
 * exposed if agents can't read any of your value," which matches this
 * section's own headline. The figure is unchanged by the exposure-model
 * fix: the substitution multiplier is capped at 1 and invisibility is
 * already 1 at this ceiling. Always a single point estimate, not the
 * mock's low-high band (that came from AGENT_DISCOVERY_RANGE, dropped
 * along with the rest of the unimplemented model).
 */
import { useRef, useState } from 'react'
import { DarkPanel, StatusChip, Button } from '../../ds/index.js'
import { computeExposure, AI_SHARE_SLIDER_MIN, AI_SHARE_SLIDER_MAX, AI_SHARE_DEFAULT_PCT, formatCurrency } from '../liteDerive.js'
import { RevenueField } from '../RevenueField.jsx'
import { track } from '../analytics.js'
import { EVENTS } from '../analyticsEvents.js'

const DEFAULT_REVENUE = 20_000_000

export function Stakes() {
  const [revenue, setRevenue] = useState(DEFAULT_REVENUE)
  const [aiSharePct, setAiSharePct] = useState(AI_SHARE_DEFAULT_PCT)
  // Stakes is a static landing section — mounted once for the page's
  // whole session, never conditionally unmounted — so this ref is
  // "once per session" in practice, and a range input's onChange
  // fires on every tick while dragging, not just once, hence the guard.
  const interactedRef = useRef(false)
  function trackFirstInteraction() {
    if (interactedRef.current) return
    interactedRef.current = true
    track(EVENTS.ESTIMATOR_INTERACTED, {})
  }

  // No brand is scored on the landing, so this is the ceiling: True
  // Value 0 -> fully invisible value. Same number this widget has
  // always shown (the substitution multiplier is capped at 1, and
  // invisibility is already 1 here), now honestly named.
  const exposure = computeExposure({ revenue, aiSharePct, trueValueScore: 0 })

  return (
    <section style={{ padding: '60px 24px 20px' }}>
      <DarkPanel pad={0} radius={20} atmos style={{ maxWidth: 1120, margin: '0 auto', overflow: 'hidden', boxShadow: 'var(--shadow-elevated)' }}>
        <div className="lite-stakes-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
          <div className="lite-stakes-left" style={{ padding: '40px 44px 42px', borderRight: '1px solid var(--dark-border)' }}>
            <div className="section-heading sm on-dark">What is invisible value <span className="accent">costing you?</span></div>
            <div style={{ marginTop: 28 }}>
              <RevenueField
                label="Annual online revenue"
                revenue={revenue}
                onRevenueChange={setRevenue}
                onInteract={trackFirstInteraction}
                tone="dark"
                labelStyle={{ fontSize: 14 }}
                valueStyle={{ fontSize: 13, fontWeight: 700, letterSpacing: '-0.01em' }}
              />
            </div>
            <div style={{ marginTop: 22, paddingTop: 22, borderTop: '1px solid var(--dark-border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 16 }}>
                <span style={{ fontSize: 14, color: 'var(--dark-muted)' }}>AI-assisted share of sales</span>
                <b className="num" style={{ fontSize: 17, fontWeight: 720, letterSpacing: '-0.02em', color: 'var(--dark-text)' }}>{aiSharePct}%</b>
              </div>
              <input
                type="range"
                min={AI_SHARE_SLIDER_MIN}
                max={AI_SHARE_SLIDER_MAX}
                value={aiSharePct}
                onChange={(e) => { setAiSharePct(+e.target.value); trackFirstInteraction() }}
                aria-label="AI-assisted share of sales"
                style={{ width: '100%', marginTop: 14, accentColor: 'var(--dark-text)' }}
              />
            </div>
            <div className="mono-label" style={{ fontSize: 9, color: 'var(--dark-faint)', marginTop: 22, paddingTop: 16, borderTop: '1px solid var(--dark-border)', lineHeight: 1.7 }}>
              MODELED FROM YOUR INPUTS · SAME MODEL AS YOUR FULL REPORT
            </div>
          </div>
          <div style={{ padding: '40px 44px 42px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <div><StatusChip tone="warning" size="sm">Modeled</StatusChip></div>
            <div style={{ fontSize: 15.5, color: 'var(--dark-text)', lineHeight: 1.5, marginTop: 20, letterSpacing: '-0.008em' }}>Modeled annual revenue exposed to invisible value</div>
            <div className="num lite-display-num" style={{ fontSize: 52, fontWeight: 740, letterSpacing: '-0.038em', lineHeight: 1, color: 'var(--dark-text)', marginTop: 20 }}>{formatCurrency(exposure)}</div>
            <div style={{ fontSize: 13.5, color: 'var(--dark-muted)', lineHeight: 1.62, marginTop: 20, maxWidth: 400 }}>
              Assumes agents can currently read none of your value — the full picture, including the value they already see, comes from a Parleo audit.
            </div>
            <div style={{ marginTop: 24 }}>
              <a href="#run" className="lite-stakes-cta" style={{ textDecoration: 'none' }}>
                <Button variant="blue" arrow>See your real number, run the free audit</Button>
              </a>
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--dark-muted)', lineHeight: 1.6, marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--dark-border)' }}>
              And it's closable: <b style={{ color: 'var(--dark-text)' }}>TrueSync</b>, Parleo's fix layer, encodes the value agents are missing.
            </div>
          </div>
        </div>
      </DarkPanel>
    </section>
  )
}
